# core/creation.py — создание сбоя, работы, обычного сообщения (канал-агностично)

import base64
import io
import logging
import uuid
from datetime import datetime as dt
from typing import Any, Callable, Awaitable, Optional

from bot_state import bot_state
from config import CONFIG, get_next_max_fa_chat_id, jira_browse_url, telegram_topic_url
from domain.constants import DATETIME_FORMAT, PROBLEM_LEVEL_POTENTIAL, INFLUENCE_CLIENTS
from utils.create_jira_fa import create_failure_issue
from utils.channel_helpers import send_to_alarm_channels
from services.max_media import download_attachment_max
from services.channel_service import ChannelService
from services.simpleone_service import SimpleOneService

logger = logging.getLogger(__name__)
channel_service = ChannelService()

# Функция ответа пользователю: текст и опционально вложения (клавиатура в MAX).
# В Telegram вызывается с одним аргументом (text), в MAX — с (text, attachments=None).
ReplyFn = Callable[..., Awaitable[Any]]


async def create_alarm(
    data: dict,
    telegram_bot: Any,
    reply_fn: ReplyFn,
    user_id: int,
) -> bool:
    """
    Создаёт сбой: Jira (опционально), SCM (опционально), канал, Петлокал.
    reply_fn вызывается для ответа пользователю (в TG или MAX).
    """
    description_text = data.get("description", "")
    issue = description_text[:100] if description_text else "Проблема не указана"
    fix_time = dt.fromisoformat(data["fix_time"]) if isinstance(data["fix_time"], str) else data["fix_time"]
    create_jira = data.get("create_jira", True)

    jira_key = None
    jira_url = None
    has_jira = False

    if create_jira:
        try:
            jira_response = await create_failure_issue(
                summary=issue,
                description=description_text,
                problem_level=PROBLEM_LEVEL_POTENTIAL,
                problem_service=data["service"],
                time_start_problem=dt.now().strftime("%Y-%m-%d %H:%M"),
                influence=INFLUENCE_CLIENTS,
            )
            if jira_response and "key" in jira_response:
                jira_key = jira_response["key"]
                alarm_id = jira_key
                jira_url = jira_browse_url(jira_key)
                has_jira = True
                logger.info("[%s] Задача в Jira создана: %s", user_id, jira_key)
            else:
                raise Exception("Не удалось получить ID задачи из Jira")
        except Exception as jira_error:
            logger.error("[%s] Ошибка создания задачи в Jira: %s", user_id, jira_error, exc_info=True)
            alarm_id = str(uuid.uuid4())[:8]
            has_jira = False
            await reply_fn(
                "⚠️ Не удалось создать задачу в Jira. Авария создана с локальным ID."
            )
    else:
        alarm_id = str(uuid.uuid4())[:8]
        has_jira = False
        logger.info("[%s] Создан сбой без Jira, ID: %s", user_id, alarm_id)

    bot_state.active_alarms[alarm_id] = {
        "issue": issue,
        "fix_time": fix_time.isoformat() if isinstance(fix_time, dt) else fix_time,
        "user_id": user_id,
        "created_at": dt.now().isoformat(),
        "jira_key": jira_key,
        "has_jira": has_jira,
        "service": data["service"],
        "description": description_text,
        "publish_petlocal": data.get("publish_petlocal", False),
    }

    base_text = None
    create_scm = data.get("create_scm", False)
    alarm_data = {"issue": issue, "service": data["service"], "description": description_text}
    if jira_url:
        base_text = await channel_service.format_alarm_scm_message(
            alarm_id, alarm_data, jira_url
        )
    elif create_scm:
        base_text = await channel_service.format_alarm_scm_message(alarm_id, alarm_data)

    fix_time_dt = fix_time if isinstance(fix_time, dt) else dt.fromisoformat(str(fix_time))
    alarm_payload = {
        "issue": description_text,
        "service": data["service"],
        "fix_time": fix_time_dt.isoformat(),
    }
    if not await channel_service.send_alarm_notification(telegram_bot, alarm_payload):
        await reply_fn("❌ Ошибка отправки в канал. Проверьте логи.")
        return False

    scm_channel_id = CONFIG["TELEGRAM"].get("SCM_CHANNEL_ID")
    scm_topic_id = None
    if scm_channel_id and base_text:
        try:
            scm_topic_id = await channel_service.create_forum_topic(
                telegram_bot,
                scm_channel_id,
                f"{alarm_id} {issue[:20]}...",
                base_text,
            )
            if scm_topic_id:
                bot_state.active_alarms[alarm_id]["scm_topic_id"] = scm_topic_id
                await channel_service.update_topic_icon(
                    telegram_bot, scm_channel_id, scm_topic_id, "🔥"
                )
        except Exception as e:
            logger.error("[%s] Ошибка создания темы SCM: %s", user_id, e, exc_info=True)

    # Чат MAX для обсуждения сбоя: выбор по числу активных сбоёв (1→чат1, 2→чат2, … 4+→чат4), привязка, переименование в "🔥 FA-XXXX", ссылка в ALARM_MAIN
    fa_chat_id = get_next_max_fa_chat_id(len(bot_state.active_alarms))
    if fa_chat_id:
        fa_chat_id = str(fa_chat_id).strip() or None
    chat_link = None  # инициализация до блока try, чтобы не было UnboundLocalError при is_configured()=False
    if fa_chat_id:
        try:
            from services.max_service import MaxService
            max_svc = MaxService()
            if max_svc.is_configured():
                bot_state.active_alarms[alarm_id]["max_chat_id"] = fa_chat_id
                title = f"🔥 {alarm_id}"[:200]
                await max_svc.set_chat_title(fa_chat_id, title)
                chat_data = await max_svc.get_chat(fa_chat_id)
                chat_link = None
                if isinstance(chat_data, dict):
                    for key in ("link", "url", "invite_link", "join_link", "joinLink", "chatLink", "inviteLink"):
                        val = chat_data.get(key)
                        if val and isinstance(val, str):
                            chat_link = val.strip()
                            break
                        if val and isinstance(val, dict) and (val.get("link") or val.get("url")):
                            chat_link = str((val.get("link") or val.get("url"))).strip()
                            break
                if not chat_link:
                    logger.debug("MAX get_chat для %s вернул ключи: %s", fa_chat_id, list(chat_data.keys()) if isinstance(chat_data, dict) else None)
                    join_link_cfg = (CONFIG.get("MAX") or {}).get("ALARM_FA_CHAT_JOIN_LINK")
                    if join_link_cfg:
                        chat_link = join_link_cfg.strip()
                    if not chat_link:
                        template = (CONFIG.get("MAX") or {}).get("CHAT_LINK_TEMPLATE")
                        if template and "{chat_id}" in template:
                            try:
                                chat_link = template.format(chat_id=fa_chat_id)
                            except Exception:
                                pass
        except Exception as e:
            logger.warning("[%s] Не удалось привязать чат MAX к сбою %s: %s", user_id, alarm_id, e)
            chat_link = None
    else:
        chat_link = None
        fa_chat_id = None
    if fa_chat_id and not chat_link:
        join_link = (CONFIG.get("MAX") or {}).get("ALARM_FA_CHAT_JOIN_LINK")
        if join_link:
            chat_link = join_link.strip()
        if not chat_link:
            template = (CONFIG.get("MAX") or {}).get("CHAT_LINK_TEMPLATE")
            if template and "{chat_id}" in template:
                try:
                    chat_link = template.format(chat_id=fa_chat_id)
                except Exception:
                    pass

    # Ссылка на тему в Telegram (t.me/c/<channel_id без -100>/<topic_id>)
    scm_topic_link = None
    if scm_channel_id and scm_topic_id:
        try:
            scm_topic_link = telegram_topic_url(scm_channel_id, scm_topic_id)
        except Exception:
            pass

    # Уведомление в ALARM_MAIN (MAX): HTML с кликабельными словами «Telegram» и «MAX» (API MAX принимает format: "html")
    def _link(url: str, label: str) -> str:
        if not url:
            return label
        safe_url = (url or "").replace("&", "&amp;")
        return f'<a href="{safe_url}">{label}</a>'

    alarm_main_chat_id = CONFIG.get("MAX", {}).get("ALARM_MAIN_CHAT_ID")
    if alarm_main_chat_id:
        try:
            from services.max_service import MaxService
            max_svc = MaxService()
            if max_svc.is_configured():
                lines = [
                    f"🆕 Новый сбой: {alarm_id}",
                    f"📋 {issue}",
                ]
                if jira_url:
                    lines.append(f"🔗 Jira: {_link(jira_url, alarm_id)}")
                line_tg = "💬 Обсуждение: тема в канале SCM (" + _link(scm_topic_link, "Telegram") + ")."
                lines.append(line_tg)
                line_max = "💬 Чат сбоя: " + _link(chat_link, "MAX") + "."
                lines.append(line_max)
                text = "\n".join(lines)
                await max_svc.send_message(alarm_main_chat_id, text, strip_html=False, format="html")
                logger.info("[%s] Уведомление о сбое %s отправлено в ALARM_MAIN", user_id, alarm_id)
        except Exception as e:
            logger.warning("[%s] Не удалось отправить в ALARM_MAIN: %s", user_id, e)

    publish_petlocal = data.get("publish_petlocal", False)
    if publish_petlocal:
        try:
            async with SimpleOneService() as simpleone:
                fix_time_str = (
                    fix_time.strftime(DATETIME_FORMAT)
                    if isinstance(fix_time, dt)
                    else str(fix_time)
                )
                html = simpleone.format_alarm_for_petlocal(
                    issue=issue,
                    service=data["service"],
                    fix_time=fix_time_str,
                    description=description_text,
                    jira_url=jira_url,
                    alarm_id=alarm_id,
                )
                result = await simpleone.create_portal_post(html)
                if not result.get("success"):
                    logger.warning("Петлокал: %s", result.get("error"))
        except Exception as e:
            logger.warning("Петлокал: %s", e, exc_info=True)

    msg = f"✅ Сбой зарегистрирован! ID: {alarm_id}"
    if jira_url:
        msg += f"\n🔗 Jira: {jira_url}"
    await reply_fn(msg)
    await bot_state.save_state()
    return True


async def create_maintenance(
    data: dict,
    telegram_bot: Any,
    reply_fn: ReplyFn,
    user_id: int,
) -> bool:
    """Создаёт регламентную работу и отправляет в канал (и опционально на Петлокал)."""
    work_id = str(uuid.uuid4())[:4]
    description = data["description"]
    start_time = (
        dt.fromisoformat(data["start_time"])
        if isinstance(data["start_time"], str)
        else data["start_time"]
    )
    end_time = (
        dt.fromisoformat(data["end_time"])
        if isinstance(data["end_time"], str)
        else data["end_time"]
    )
    unavailable_services = data.get("unavailable_services", "не указано")

    bot_state.active_maintenances[work_id] = {
        "description": description,
        "start_time": start_time.isoformat() if isinstance(start_time, dt) else start_time,
        "end_time": end_time.isoformat() if isinstance(end_time, dt) else end_time,
        "unavailable_services": unavailable_services,
        "user_id": user_id,
        "created_at": dt.now().isoformat(),
        "publish_petlocal": data.get("publish_petlocal", False),
    }

    maint_text = (
        f"🔧 <b>Проводим плановые технические работы – станет ещё лучше!</b>\n"
        f"• <b>Описание:</b> {description}\n"
        f"• <b>Начало:</b> {start_time.strftime(DATETIME_FORMAT)}\n"
        f"• <b>Конец:</b> {end_time.strftime(DATETIME_FORMAT)}\n"
        f"• <b>Недоступно:</b> {unavailable_services}"
    )
    if not await send_to_alarm_channels(telegram_bot, maint_text):
        await reply_fn("❌ Ошибка отправки в канал.")
        return False

    publish_petlocal = data.get("publish_petlocal", False)
    if publish_petlocal:
        try:
            async with SimpleOneService() as simpleone:
                html = simpleone.format_maintenance_for_petlocal(
                    description=description,
                    start_time=start_time.strftime(DATETIME_FORMAT),
                    end_time=end_time.strftime(DATETIME_FORMAT),
                    unavailable_services=unavailable_services,
                )
                await simpleone.create_portal_post(html)
        except Exception as e:
            logger.warning("Петлокал: %s", e, exc_info=True)

    await reply_fn(f"✅ Работы зарегистрированы! ID: {work_id}")
    await bot_state.save_state()
    return True


async def send_regular_message(
    data: dict,
    telegram_bot: Any,
    reply_fn: ReplyFn,
    user_id: int,
) -> bool:
    """Отправляет обычное сообщение в канал (и опционально на Петлокал). Поддерживает фото из TG (file_id) и MAX (url)."""
    message_text = data["message_text"]
    regular_text = f"💬 <b>Сообщение от администратора:</b>\n{message_text}\n"
    photo_file_id = data.get("photo_file_id")
    photo_url_from_max = (data.get("photo_url_from_max") or "").strip() or None
    if not await send_to_alarm_channels(
        telegram_bot,
        regular_text,
        photo_file_id=photo_file_id,
        photo_url=photo_url_from_max,
    ):
        await reply_fn("❌ Ошибка отправки в канал.")
        return False

    publish_petlocal = data.get("publish_petlocal", False)
    if publish_petlocal:
        try:
            image_base64 = None
            image_media_type = "image/jpeg"
            if photo_file_id and telegram_bot:
                try:
                    file = await telegram_bot.get_file(photo_file_id)
                    buf = io.BytesIO()
                    await telegram_bot.download_file(file.file_path, buf)
                    image_bytes = buf.getvalue()
                    if image_bytes:
                        image_base64 = base64.b64encode(image_bytes).decode("ascii")
                        if getattr(file, "file_path", "") and ".png" in (file.file_path or "").lower():
                            image_media_type = "image/png"
                except Exception as e:
                    logger.warning("Не удалось загрузить фото (TG) для Петлокала: %s", e, exc_info=True)
            elif photo_url_from_max:
                try:
                    downloaded = await download_attachment_max(photo_url_from_max, "image", "max_photo.jpg")
                    if downloaded:
                        image_bytes, image_name = downloaded
                        image_base64 = base64.b64encode(image_bytes).decode("ascii")
                        lower_name = (image_name or "").lower()
                        if lower_name.endswith(".png"):
                            image_media_type = "image/png"
                        elif lower_name.endswith(".gif"):
                            image_media_type = "image/gif"
                        elif lower_name.endswith(".webp"):
                            image_media_type = "image/webp"
                        else:
                            image_media_type = "image/jpeg"
                except Exception as e:
                    logger.warning("Не удалось загрузить фото (MAX) для Петлокала: %s", e, exc_info=True)
            async with SimpleOneService() as simpleone:
                html = simpleone.format_regular_message_for_petlocal(
                    message_text,
                    image_base64=image_base64,
                    image_media_type=image_media_type,
                )
                await simpleone.create_portal_post(html)
        except Exception as e:
            logger.warning("Петлокал: %s", e, exc_info=True)

    await reply_fn("✅ Сообщение отправлено")
    await bot_state.save_state()
    return True
