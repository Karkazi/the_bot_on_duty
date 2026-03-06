"""
Мост TG -> MAX: сообщения из темы SCM пересылаются в чат сбоя (FA-XXXX) в MAX.
Поддерживаются текст, фото, документы и видео.
"""
import logging
import tempfile
import os
from aiogram import Router, F
from aiogram.types import Message

from config import CONFIG
from bot_state import bot_state
from services.max_service import MaxService
from services.max_media import (
    upload_image_max,
    upload_file_max,
    build_max_attachments_for_message,
)

logger = logging.getLogger(__name__)
router = Router(name="bridge_scm_max")


def _find_max_chat_for_topic(topic_id: int):
    """Возвращает (alarm_id, max_chat_id) для топика SCM или (None, None)."""
    for alarm_id, info in list(bot_state.active_alarms.items()):
        if info.get("scm_topic_id") != topic_id:
            continue
        max_chat_id = info.get("max_chat_id")
        if max_chat_id:
            return alarm_id, str(max_chat_id).strip()
    return None, None


async def _bridge_text_and_or_attachments_to_max(
    message: Message,
    topic_id: int,
    text_line: str,
    temp_file_path: str | None,
    is_image: bool,
) -> None:
    """Отправляет в MAX сообщение с текстом и опционально одним вложением (файл с диска)."""
    alarm_id, max_chat_id = _find_max_chat_for_topic(topic_id)
    if not max_chat_id:
        return
    svc = MaxService()
    if not svc.is_configured():
        return
    attachment_tokens = []
    if temp_file_path and os.path.isfile(temp_file_path):
        if is_image:
            token = await upload_image_max(temp_file_path)
            if token:
                attachment_tokens = build_max_attachments_for_message([token], [])
            else:
                # Fallback: отправить фото как файл (документ), чтобы в MAX хотя бы было вложение
                token = await upload_file_max(temp_file_path, mime_type="image/jpeg")
                if token:
                    name = os.path.basename(temp_file_path)
                    attachment_tokens = build_max_attachments_for_message([], [(token, name)])
                    logger.info("Мост TG->MAX: фото загружено как файл (upload_image не вернул token)")
                else:
                    logger.warning("Мост TG->MAX: загрузка фото в MAX не удалась (image и file), отправляем только текст")
        else:
            token = await upload_file_max(temp_file_path)
            if token:
                name = os.path.basename(temp_file_path)
                attachment_tokens = build_max_attachments_for_message([], [(token, name)])
        try:
            os.unlink(temp_file_path)
        except Exception:
            pass
    if attachment_tokens:
        await svc.send_message_with_attachments(max_chat_id, text_line, attachment_tokens=attachment_tokens)
    else:
        await svc.send_message(max_chat_id, text_line, strip_html=True)
    if alarm_id:
        logger.debug("Мост TG->MAX: сбой %s, чат %s (%s)", alarm_id, max_chat_id, "с вложением" if attachment_tokens else "текст")


@router.message(F.text)
async def bridge_scm_topic_to_max(message: Message) -> None:
    """Если сообщение в канале SCM в топике — переслать в чат MAX (max_chat_id сбоя). Только текст."""
    scm_channel_id = CONFIG.get("TELEGRAM", {}).get("SCM_CHANNEL_ID")
    if not scm_channel_id or not getattr(message, "message_thread_id", None):
        return
    try:
        scm_id = int(scm_channel_id)
    except (TypeError, ValueError):
        return
    if message.chat.id != scm_id:
        return
    if message.from_user and getattr(message.from_user, "is_bot", False):
        return
    topic_id = message.message_thread_id
    name = (message.from_user and (message.from_user.full_name or message.from_user.username)) or "TG"
    text = f"[TG, {name}]: {message.text or ''}"
    await _bridge_text_and_or_attachments_to_max(message, topic_id, text, None, False)


@router.message(F.photo)
async def bridge_scm_photo_to_max(message: Message) -> None:
    """Фото из темы SCM — скачать, загрузить в MAX, отправить в чат сбоя."""
    scm_channel_id = CONFIG.get("TELEGRAM", {}).get("SCM_CHANNEL_ID")
    if not scm_channel_id or not getattr(message, "message_thread_id", None):
        return
    try:
        scm_id = int(scm_channel_id)
    except (TypeError, ValueError):
        return
    if message.chat.id != scm_id:
        return
    if message.from_user and getattr(message.from_user, "is_bot", False):
        return
    topic_id = message.message_thread_id
    _, max_chat_id = _find_max_chat_for_topic(topic_id)
    if not max_chat_id:
        return
    name = (message.from_user and (message.from_user.full_name or message.from_user.username)) or "TG"
    caption = (message.caption or "").strip()
    text_line = f"[TG, {name}]: {caption}" if caption else f"[TG, {name}]: (фото)"
    photo = message.photo[-1]
    path = None
    try:
        f = await message.bot.get_file(photo.file_id)
        suffix = ".jpg"
        if getattr(f, "file_path", "") and ".png" in (f.file_path or "").lower():
            suffix = ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="bridge_photo_") as tmp:
            path = tmp.name
        await message.bot.download_file(f.file_path, path)
        await _bridge_text_and_or_attachments_to_max(message, topic_id, text_line, path, is_image=True)
    except Exception as e:
        logger.warning("Мост TG->MAX (фото): %s", e)
        if path and os.path.isfile(path):
            try:
                os.unlink(path)
            except Exception:
                pass


@router.message(F.document)
async def bridge_scm_document_to_max(message: Message) -> None:
    """Документ из темы SCM — скачать, загрузить в MAX, отправить в чат сбоя."""
    scm_channel_id = CONFIG.get("TELEGRAM", {}).get("SCM_CHANNEL_ID")
    if not scm_channel_id or not getattr(message, "message_thread_id", None):
        return
    try:
        scm_id = int(scm_channel_id)
    except (TypeError, ValueError):
        return
    if message.chat.id != scm_id:
        return
    if message.from_user and getattr(message.from_user, "is_bot", False):
        return
    topic_id = message.message_thread_id
    _, max_chat_id = _find_max_chat_for_topic(topic_id)
    if not max_chat_id:
        return
    name = (message.from_user and (message.from_user.full_name or message.from_user.username)) or "TG"
    caption = (message.caption or "").strip()
    text_line = f"[TG, {name}]: {caption}" if caption else f"[TG, {name}]: (файл)"
    doc = message.document
    path = None
    try:
        f = await message.bot.get_file(doc.file_id)
        ext = os.path.splitext(doc.file_name or "")[1] or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext, prefix="bridge_doc_") as tmp:
            path = tmp.name
        await message.bot.download_file(f.file_path, path)
        await _bridge_text_and_or_attachments_to_max(message, topic_id, text_line, path, is_image=False)
    except Exception as e:
        logger.warning("Мост TG->MAX (документ): %s", e)
        if path and os.path.isfile(path):
            try:
                os.unlink(path)
            except Exception:
                pass


@router.message(F.video)
async def bridge_scm_video_to_max(message: Message) -> None:
    """Видео из темы SCM — скачать, загрузить в MAX как файл, отправить в чат сбоя."""
    scm_channel_id = CONFIG.get("TELEGRAM", {}).get("SCM_CHANNEL_ID")
    if not scm_channel_id or not getattr(message, "message_thread_id", None):
        return
    try:
        scm_id = int(scm_channel_id)
    except (TypeError, ValueError):
        return
    if message.chat.id != scm_id:
        return
    if message.from_user and getattr(message.from_user, "is_bot", False):
        return
    topic_id = message.message_thread_id
    _, max_chat_id = _find_max_chat_for_topic(topic_id)
    if not max_chat_id:
        return
    name = (message.from_user and (message.from_user.full_name or message.from_user.username)) or "TG"
    caption = (message.caption or "").strip()
    text_line = f"[TG, {name}]: {caption}" if caption else f"[TG, {name}]: (видео)"
    video = message.video
    path = None
    try:
        f = await message.bot.get_file(video.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", prefix="bridge_video_") as tmp:
            path = tmp.name
        await message.bot.download_file(f.file_path, path)
        await _bridge_text_and_or_attachments_to_max(message, topic_id, text_line, path, is_image=False)
    except Exception as e:
        logger.warning("Мост TG->MAX (видео): %s", e)
        if path and os.path.isfile(path):
            try:
                os.unlink(path)
            except Exception:
                pass
