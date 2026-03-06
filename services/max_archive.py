"""
Архивация истории чата MAX (FA-XXXX) при закрытии сбоя.
- Если есть задача в JIRA: добавляем историю как комментарий + вложения как аттачи к задаче; при успехе очищаем чат.
- Если комментарий в JIRA не удалось добавить: сохраняем на диск, очищаем чат, пишем об этом.
- Если задачи в JIRA нет: сохраняем на диск, очищаем чат.
"""
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.max_service import MaxService
from services.max_media import download_attachment_max
from utils.jira_comment import add_comment_to_jira_issue
from utils.jira_attachments import add_attachments_to_jira_issue

logger = logging.getLogger(__name__)

ARCHIVE_DIR = Path(__file__).resolve().parent.parent / "data" / "archive" / "alarms"


def _format_messages_for_file(messages: List[Dict[str, Any]]) -> str:
    """Форматирует список сообщений в текст для файла (включая строки про вложения)."""
    lines = []
    for m in messages:
        t = m.get("time") or ""
        name = m.get("sender_name") or "?"
        text = (m.get("text") or "").replace("\n", " ")
        lines.append(f"[{t}] {name}: {text}")
        for att in m.get("attachments") or []:
            fn = att.get("filename") or att.get("url", "")[:30] or "вложение"
            lines.append(f"[{t}] {name}: [вложение: {fn}]")
    return "\n".join(lines) if lines else "(нет сообщений)"


def _format_messages_for_jira(messages: List[Dict[str, Any]]) -> str:
    """Форматирует список сообщений для комментария в JIRA (plain text), со строками про вложения."""
    lines = []
    for m in messages:
        t = m.get("time") or ""
        name = m.get("sender_name") or "?"
        text = (m.get("text") or "").replace("\r\n", "\n")
        lines.append(f"[{t}] {name}: {text}")
        for att in m.get("attachments") or []:
            fn = att.get("filename") or att.get("url", "")[:30] or "вложение"
            lines.append(f"[{t}] {name}: [вложение: {fn}]")
    return "\n".join(lines) if lines else "(нет сообщений)"


def _save_archive_to_disk(
    alarm_id: str,
    max_chat_id: str,
    messages: List[Dict[str, Any]],
) -> bool:
    """Сохраняет историю чата в файл в data/archive/alarms/. Возвращает True при успехе."""
    if not messages:
        return True
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in alarm_id)
    filename = ARCHIVE_DIR / f"{safe_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    try:
        body = f"# Архив чата MAX по сбою {alarm_id}\n# chat_id: {max_chat_id}\n\n"
        body += _format_messages_for_file(messages)
        filename.write_text(body, encoding="utf-8")
        logger.info("История чата %s сохранена в %s", max_chat_id, filename)
        return True
    except Exception as e:
        logger.warning("Не удалось записать архив чата %s: %s", max_chat_id, e)
        return False


async def _clear_chat_and_send(
    svc: MaxService,
    max_chat_id: str,
    messages: List[Dict[str, Any]],
    final_message: str,
) -> None:
    """
    Очищает чат и отправляет одно итоговое сообщение.
    Сначала пробует clear_chat_messages (удаляет всю историю, включая служебные сообщения о смене названия).
    Если API не поддерживает очистку — удаляет по одному сообщению по mid (служебные останутся).
    """
    cleared = await svc.clear_chat_messages(max_chat_id)
    if not cleared and messages:
        deleted = 0
        for m in messages:
            mid = m.get("mid")
            if mid:
                ok = await svc.delete_message(max_chat_id, mid)
                if ok:
                    deleted += 1
        if deleted == 0 and any(m.get("mid") for m in messages):
            logger.warning("MAX: не удалось удалить сообщения в чате %s (возможно, другой формат API)", max_chat_id)
        else:
            logger.debug("MAX: удалено сообщений по одному: %s (служебные сообщения о смене названия останутся)", deleted)
    ok_send = await svc.send_message(max_chat_id, final_message, strip_html=True)
    if not ok_send:
        logger.warning("MAX: не удалось отправить итоговое сообщение в чат %s", max_chat_id)


async def process_max_chat_on_alarm_close(
    alarm_id: str,
    max_chat_id: str,
    jira_key: Optional[str] = None,
    max_messages_count: int = 100,
) -> bool:
    """
    Обрабатывает чат MAX при закрытии сбоя:
    - Если есть jira_key: добавляем историю как комментарий в JIRA и все вложения из чата как attachments.
      Чат очищается только когда комментарий и вложения успешно загружены в JIRA.
      Если JIRA недоступна или часть вложений не загрузилась — чат НЕ очищается (чтобы можно было повторить экспорт).
    - Если jira_key нет: архивируем на диск, очищаем чат, сообщение «Сбой закрыт. Информация архивирована на диск. Чат очищен».

    Возвращает True, если MAX настроен и обработка выполнена (в т.ч. при пустой истории).
    """
    svc = MaxService()
    if not svc.is_configured():
        logger.warning("MAX не настроен — чат %s не архивирован для сбоя %s", max_chat_id, alarm_id)
        return False

    logger.info("Архивация чата MAX для сбоя %s (chat_id=%s, jira_key=%s)", alarm_id, max_chat_id, jira_key)
    messages = await svc.get_messages(max_chat_id, count=max_messages_count)
    if messages is None:
        messages = []
        logger.warning("Не удалось получить историю чата MAX %s для сбоя %s", max_chat_id, alarm_id)

    formatted = _format_messages_for_jira(messages)
    header = f"Архив чата MAX по сбою {alarm_id}\n\n"
    body_for_jira = header + formatted if formatted else header + "(нет сообщений)"

    if jira_key and (jira_key or "").strip():
        jira_key = jira_key.strip()
        added = await add_comment_to_jira_issue(jira_key, body_for_jira)
        attachment_paths = []
        expected_attachments = 0
        try:
            for m in messages:
                for att in m.get("attachments") or []:
                    url = (att.get("url") or "").strip()
                    if not url or not url.startswith("http"):
                        continue
                    expected_attachments += 1
                    content, name = await download_attachment_max(
                        url,
                        att.get("type", ""),
                        att.get("filename") or "",
                    )
                    if not content:
                        continue
                    ext = os.path.splitext(name)[1] if name and "." in name else ".bin"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, prefix="archive_") as tf:
                        tf.write(content)
                        attachment_paths.append(tf.name)
            added_count = 0
            attempted_count = 0
            if attachment_paths:
                added_count, attempted_count = await add_attachments_to_jira_issue(jira_key, attachment_paths)
                logger.info(
                    "К задаче JIRA %s добавлено вложений из чата MAX: %s/%s (ожидалось URL-вложений: %s)",
                    jira_key, added_count, attempted_count, expected_attachments
                )
            attachments_ok = (
                expected_attachments == 0
                or (attachment_paths and attempted_count > 0 and added_count == attempted_count)
            )
        except Exception as e:
            logger.warning("Не удалось добавить вложения из чата MAX в JIRA %s: %s", jira_key, e)
            attachments_ok = False
        for p in attachment_paths:
            try:
                if os.path.isfile(p):
                    os.unlink(p)
            except Exception:
                pass
        if added and attachments_ok:
            await _clear_chat_and_send(
                svc,
                max_chat_id,
                messages,
                "Сбой закрыт. Информация архивирована в задаче JIRA.",
            )
            return True
        _save_archive_to_disk(alarm_id, max_chat_id, messages)
        reason = []
        if not added:
            reason.append("комментарий в JIRA не добавлен")
        if not attachments_ok:
            reason.append("вложения в JIRA добавлены не полностью")
        reason_text = "; ".join(reason) if reason else "экспорт в JIRA не завершён"
        logger.warning(
            "Сбой %s: чат MAX не очищен, %s. Повторите закрытие после устранения причины.",
            alarm_id, reason_text
        )
        await svc.send_message(
            max_chat_id,
            "Сбой закрыт, но архив в JIRA завершился с ошибкой. Чат не очищен, чтобы не потерять вложения. "
            "После устранения ошибки повторите экспорт/закрытие.",
            strip_html=True,
        )
        return False

    _save_archive_to_disk(alarm_id, max_chat_id, messages)
    await _clear_chat_and_send(
        svc,
        max_chat_id,
        messages,
        "Сбой закрыт. Информация архивирована на диск. Чат очищен.",
    )
    return True


async def archive_max_alarm_chat(
    alarm_id: str,
    max_chat_id: str,
    max_messages_count: int = 100,
    delete_chat: bool = True,
) -> bool:
    """
    Устаревший вариант: только сохранение в файл и опционально удаление чата.
    Для закрытия сбоя используйте process_max_chat_on_alarm_close.
    """
    svc = MaxService()
    if not svc.is_configured():
        logger.debug("MAX не настроен, архивация чата пропущена")
        return False
    messages = await svc.get_messages(max_chat_id, count=max_messages_count)
    if messages is None:
        logger.warning("Не удалось получить историю чата MAX %s для сбоя %s", max_chat_id, alarm_id)
    else:
        _save_archive_to_disk(alarm_id, max_chat_id, messages)
    if delete_chat:
        return await svc.delete_chat(max_chat_id)
    return True
