# core/creation.py — создание сбоя, работы, обычного сообщения (MAX)

import asyncio
import base64
import logging
import uuid
from datetime import datetime as dt
from typing import Any, Callable, Awaitable, Optional

from bot_state import bot_state
from config import CONFIG, get_next_max_fa_chat_id, jira_browse_url, ktalk_emergency_url
from domain.constants import (
    DATETIME_FORMAT,
    PROBLEM_LEVEL_POTENTIAL,
    PROBLEM_SERVICE_OTHER,
    INFLUENCE_CLIENTS,
    format_alarm_service_for_display,
)
from utils.bot_time import bot_now_naive
from utils.create_jira_fa import create_failure_issue
from utils.channel_helpers import send_to_alarm_channel
from services.max_media import download_attachment_max
from services.responsibles_service import notify_alarm_responsibles
from services.simpleone_service import SimpleOneService
from services.message_formatter import MessageFormatter
from services.alarm_history_service import append_alarm_created

logger = logging.getLogger(__name__)

ReplyFn = Callable[..., Awaitable[Any]]


async def create_alarm(
    data: dict,
    reply_fn: ReplyFn,
    user_id: int,
    author_messenger: str = "max",
) -> bool:
    """Создаёт сбой: Jira (опционально), канал MAX, FA-чат, ALARM_MAIN, Петлокал."""
    description_text = data.get("description", "")
    issue = description_text[:100] if description_text else "Проблема не указана"
    fix_time = dt.fromisoformat(data["fix_time"]) if isinstance(data["fix_time"], str) else data["fix_time"]
    create_jira = data.get("create_jira", True)

    if (data.get("service") or "").strip() == PROBLEM_SERVICE_OTHER:
        if not (data.get("service_other_spec") or "").strip():
            await reply_fn("⚠️ Для сервиса «Другое» нужно указать уточнение. Начните создание сбоя заново.")
            return False

    jira_key = None
    jira_url = None
    has_jira = False

    if create_jira:
        try:
            jira_description = description_text
            _spec = (data.get("service_other_spec") or "").strip()
            if (data.get("service") or "").strip() == PROBLEM_SERVICE_OTHER and _spec:
                jira_description = f"{description_text}\n\nУточнение сервиса «{PROBLEM_SERVICE_OTHER}»: {_spec}"
            jira_response = await create_failure_issue(
                summary=issue,
                description=jira_description,
                problem_level=PROBLEM_LEVEL_POTENTIAL,
                problem_service=data["service"],
                time_start_problem=bot_now_naive().strftime("%Y-%m-%d %H:%M"),
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
            await reply_fn("⚠️ Не удалось создать задачу в Jira. Авария создана с локальным ID.")
    else:
        alarm_id = str(uuid.uuid4())[:8]
        has_jira = False
        logger.info("[%s] Создан сбой без Jira, ID: %s", user_id, alarm_id)

    bot_state.active_alarms[alarm_id] = {
        "issue": issue,
        "fix_time": fix_time.isoformat() if isinstance(fix_time, dt) else fix_time,
        "user_id": user_id,
        "author_messenger": author_messenger,
        "created_at": bot_now_naive().isoformat(),
        "jira_key": jira_key,
        "has_jira": has_jira,
        "service": data["service"],
        "service_other_spec": (data.get("service_other_spec") or "").strip() or None,
        "description": description_text,
        "publish_petlocal": data.get("publish_petlocal", False),
    }
    append_alarm_created(alarm_id=alarm_id, alarm_info=bot_state.active_alarms[alarm_id])

    used_fa_chats = {
        str(a["max_chat_id"]).strip()
        for a in bot_state.active_alarms.values()
        if a.get("max_chat_id")
    }
    fa_chat_id = get_next_max_fa_chat_id(used_fa_chats)
    if fa_chat_id:
        fa_chat_id = str(fa_chat_id).strip() or None

    fix_time_dt = fix_time if isinstance(fix_time, dt) else dt.fromisoformat(str(fix_time))
    service_display = format_alarm_service_for_display(data.get("service"), data.get("service_other_spec"))

    chat_link: Optional[str] = None

    async def _task_channel() -> None:
        text = (
            f"🚨 Технический сбой\n"
            f"• Проблема: {description_text}\n"
            f"• Сервис: {service_display}\n"
            f"• Исправим до: {fix_time_dt.strftime(DATETIME_FORMAT)}\n"
            f"• Мы уже работаем над устранением сбоя. Спасибо за ваше терпение и понимание!"
        )
        if not await send_to_alarm_channel(text):
            logger.warning("[%s] Не удалось отправить в канал MAX для сбоя %s", user_id, alarm_id)

    async def _task_max_chat() -> None:
        nonlocal chat_link
        if not fa_chat_id:
            return
        try:
            from services.max_service import MaxService
            max_svc = MaxService()
            if not max_svc.is_configured():
                return
            cfg = CONFIG.get("MAX") or {}
            join_links_by_chat = cfg.get("ALARM_FA_CHAT_JOIN_LINKS") or {}
            per_chat_join_link = str(join_links_by_chat.get(str(fa_chat_id), "") or "").strip()
            preferred_join_link = (cfg.get("ALARM_FA_CHAT_JOIN_LINK") or "").strip()
            bot_state.active_alarms[alarm_id]["max_chat_id"] = fa_chat_id
            await max_svc.set_chat_title(fa_chat_id, f"🔥 {alarm_id}"[:200])
            if per_chat_join_link:
                chat_link = per_chat_join_link
                return
            if preferred_join_link:
                chat_link = preferred_join_link
                return
            chat_data = await max_svc.get_chat(fa_chat_id)
            if isinstance(chat_data, dict):
                for key in ("link", "url", "invite_link", "join_link", "joinLink", "chatLink", "inviteLink"):
                    val = chat_data.get(key)
                    if val and isinstance(val, str):
                        chat_link = val.strip()
                        return
                    if val and isinstance(val, dict) and (val.get("link") or val.get("url")):
                        chat_link = str((val.get("link") or val.get("url"))).strip()
                        return
            if not chat_link and "{chat_id}" in (cfg.get("CHAT_LINK_TEMPLATE") or ""):
                try:
                    chat_link = (cfg.get("CHAT_LINK_TEMPLATE") or "").format(chat_id=fa_chat_id)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("[%s] Не удалось привязать чат MAX к сбою %s: %s", user_id, alarm_id, e)

    await asyncio.gather(_task_channel(), _task_max_chat())

    if fa_chat_id and not chat_link:
        cfg = CONFIG.get("MAX") or {}
        join_links_by_chat = cfg.get("ALARM_FA_CHAT_JOIN_LINKS") or {}
        chat_link = str(join_links_by_chat.get(str(fa_chat_id), "") or "").strip()
        if not chat_link:
            chat_link = (cfg.get("ALARM_FA_CHAT_JOIN_LINK") or "").strip()
        if not chat_link and "{chat_id}" in (cfg.get("CHAT_LINK_TEMPLATE") or ""):
            try:
                chat_link = (cfg.get("CHAT_LINK_TEMPLATE") or "").format(chat_id=fa_chat_id)
            except Exception:
                pass

    unified_text_html = MessageFormatter.format_alarm_unified_html(
        alarm_id=alarm_id,
        description=description_text,
        service=data["service"],
        jira_url=jira_url,
        max_chat_url=chat_link,
        ktalk_url=ktalk_emergency_url() or None,
        service_other_spec=data.get("service_other_spec"),
    )
    fa_text = MessageFormatter.format_alarm_fa_text(
        alarm_id=alarm_id,
        description=description_text,
        service=data["service"],
        jira_key=jira_key,
        service_other_spec=data.get("service_other_spec"),
        ktalk_url=ktalk_emergency_url() or None,
    )

    alarm_main_chat_id = CONFIG.get("MAX", {}).get("ALARM_MAIN_CHAT_ID")
    publish_petlocal = data.get("publish_petlocal", False)

    async def _task_alarm_main() -> None:
        if not alarm_main_chat_id:
            return
        try:
            from services.max_service import MaxService
            max_svc = MaxService()
            if max_svc.is_configured():
                await max_svc.send_message(alarm_main_chat_id, unified_text_html, strip_html=False, format="html")
        except Exception as e:
            logger.warning("[%s] ALARM_MAIN: %s", user_id, e)

    async def _task_fa_chat_message() -> None:
        if not fa_chat_id:
            return
        try:
            from services.max_service import MaxService
            max_svc = MaxService()
            if max_svc.is_configured():
                await max_svc.send_message(fa_chat_id, fa_text, strip_html=True)
                await notify_alarm_responsibles(
                    max_service=max_svc,
                    fa_chat_id=fa_chat_id,
                    initiator_user_id=user_id,
                    service_name=data.get("service") or "",
                    service_other_spec=data.get("service_other_spec"),
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[%s] FA-чат %s: %s", user_id, fa_chat_id, e)

    async def _task_petlocal() -> None:
        if not publish_petlocal:
            return
        try:
            async with SimpleOneService() as simpleone:
                fix_time_str = fix_time.strftime(DATETIME_FORMAT) if isinstance(fix_time, dt) else str(fix_time)
                html = simpleone.format_alarm_for_petlocal(
                    issue=issue, service=service_display, fix_time=fix_time_str,
                    description=description_text, jira_url=jira_url, alarm_id=alarm_id,
                )
                result = await simpleone.create_portal_post(html)
                if not result.get("success"):
                    logger.warning("Петлокал: %s", result.get("error"))
        except Exception as e:
            logger.warning("Петлокал: %s", e, exc_info=True)

    await asyncio.gather(_task_alarm_main(), _task_fa_chat_message(), _task_petlocal())

    msg = f"✅ Сбой зарегистрирован! ID: {alarm_id}"
    if jira_url:
        msg += f"\n🔗 Jira: {jira_url}"
    await reply_fn(msg)
    await bot_state.save_state()
    return True


async def create_maintenance(
    data: dict,
    reply_fn: ReplyFn,
    user_id: int,
    author_messenger: str = "max",
) -> bool:
    """Регламентная работа: канал MAX и опционально Петлокал."""
    work_id = str(uuid.uuid4())[:4]
    description = data["description"]
    start_time = dt.fromisoformat(data["start_time"]) if isinstance(data["start_time"], str) else data["start_time"]
    end_time = dt.fromisoformat(data["end_time"]) if isinstance(data["end_time"], str) else data["end_time"]
    unavailable_services = data.get("unavailable_services", "не указано")
    send_to_max = data.get("send_to_max", data.get("send_to_telegram_max", True))
    publish_petlocal = data.get("publish_petlocal", False)

    bot_state.active_maintenances[work_id] = {
        "description": description,
        "start_time": start_time.isoformat() if isinstance(start_time, dt) else start_time,
        "end_time": end_time.isoformat() if isinstance(end_time, dt) else end_time,
        "unavailable_services": unavailable_services,
        "user_id": user_id,
        "author_messenger": author_messenger,
        "created_at": bot_now_naive().isoformat(),
        "publish_petlocal": publish_petlocal,
    }

    maint_text = (
        f"🔧 Проводим плановые технические работы – станет ещё лучше!\n"
        f"• Описание: {description}\n"
        f"• Начало: {start_time.strftime(DATETIME_FORMAT)}\n"
        f"• Конец: {end_time.strftime(DATETIME_FORMAT)}\n"
        f"• Недоступно: {unavailable_services}"
    )

    failed_channels: list[str] = []

    async def _task_channels() -> None:
        if not send_to_max:
            return
        if not await send_to_alarm_channel(maint_text, strip_html=True):
            failed_channels.append("MAX")

    async def _task_petlocal() -> None:
        if not publish_petlocal:
            return
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
            failed_channels.append("Петлокал")
            logger.warning("Петлокал %s: %s", work_id, e, exc_info=True)

    await asyncio.gather(_task_channels(), _task_petlocal())
    await bot_state.save_state()

    if failed_channels:
        await reply_fn(f"✅ Работы зарегистрированы (ID: {work_id}), ошибки: {', '.join(failed_channels)}.")
    else:
        await reply_fn(f"✅ Работы зарегистрированы! ID: {work_id}")
    return True


async def send_regular_message(
    data: dict,
    reply_fn: ReplyFn,
    user_id: int,
) -> bool:
    """Обычное сообщение в канал MAX и опционально Петлокал."""
    message_text = data["message_text"]
    regular_text = f"💬 Сообщение от администратора:\n{message_text}\n"
    photo_url_from_max = (data.get("photo_url_from_max") or "").strip() or None
    publish_petlocal = data.get("publish_petlocal", False)
    failed: list[str] = []

    async def _task_channels() -> None:
        if not await send_to_alarm_channel(regular_text):
            failed.append("MAX")

    async def _task_petlocal() -> None:
        if not publish_petlocal:
            return
        try:
            image_base64 = None
            image_media_type = "image/jpeg"
            if photo_url_from_max:
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
            async with SimpleOneService() as simpleone:
                html = simpleone.format_regular_message_for_petlocal(
                    message_text, image_base64=image_base64, image_media_type=image_media_type,
                )
                await simpleone.create_portal_post(html)
        except Exception as e:
            failed.append("Петлокал")
            logger.warning("Петлокал: %s", e, exc_info=True)

    await asyncio.gather(_task_channels(), _task_petlocal())
    msg = "✅ Сообщение отправлено"
    if failed:
        msg += f"\n⚠️ Частичные сбои: {', '.join(failed)}."
    await reply_fn(msg)
    await bot_state.save_state()
    return True
