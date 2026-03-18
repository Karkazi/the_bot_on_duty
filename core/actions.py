# core/actions.py — остановка и продление событий (канал-агностично)

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, Awaitable, Any, Optional

from bot_state import bot_state
from config import CONFIG
from utils.channel_helpers import send_to_alarm_channels
from handlers.manage.scm import handle_scm_alarm_close
from services.simpleone_service import SimpleOneService
from services.max_archive import process_max_chat_on_alarm_close
from services.max_service import MaxService

logger = logging.getLogger(__name__)

ReplyFn = Callable[[str], Awaitable[Any]]


async def stop_alarm(
    alarm_id: str,
    telegram_bot: Any,
    reply_fn: ReplyFn,
) -> bool:
    """
    Останавливает сбой. Все операции (MAX→JIRA, SCM, Петлокал, каналы) выполняются параллельно.
    Ошибка одного сервиса не блокирует остальные; сбой всегда помечается как остановленный.
    """
    alarm_info = bot_state.active_alarms.get(alarm_id)
    if not alarm_info:
        await reply_fn("❌ Сбой не найден.")
        return False

    alarm_copy = dict(alarm_info)
    max_chat_id = alarm_info.get("max_chat_id")
    if max_chat_id is not None:
        max_chat_id = str(max_chat_id).strip() or None
    if not max_chat_id:
        chat_ids = (CONFIG.get("MAX") or {}).get("ALARM_FA_CHAT_IDS") or []
        if chat_ids:
            max_chat_id = str(chat_ids[0]).strip() or None
        if max_chat_id:
            logger.info("Сбой %s без max_chat_id — используем первый чат из ALARM_FA_CHAT_IDS", alarm_id)
    jira_key = alarm_info.get("jira_key")
    failed: list[str] = []

    async def _task_max_archive() -> None:
        if not max_chat_id:
            return
        try:
            max_svc = MaxService()
            if not max_svc.is_configured():
                return
            await max_svc.set_chat_title(max_chat_id, f"✅ {alarm_id}"[:200])
            ok = await process_max_chat_on_alarm_close(alarm_id, max_chat_id, jira_key=jira_key)
            if jira_key and not ok:
                failed.append("архив MAX→JIRA")
        except Exception as e:
            logger.warning("Ошибка архивации чата MAX для сбоя %s: %s", alarm_id, e, exc_info=True)
            failed.append("архив MAX→JIRA")

    async def _task_scm() -> None:
        try:
            await handle_scm_alarm_close(telegram_bot, alarm_id, alarm_copy)
        except Exception as e:
            logger.warning("Ошибка SCM при закрытии сбоя %s: %s", alarm_id, e, exc_info=True)
            failed.append("SCM (Telegram)")

    async def _task_petlocal() -> None:
        if not alarm_copy.get("publish_petlocal", True):
            return
        try:
            closed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
            async with SimpleOneService() as simpleone:
                html = simpleone.format_alarm_closed_for_petlocal(
                    alarm_id=alarm_id,
                    issue=alarm_copy.get("issue", "не указано"),
                    closed_at=closed_at,
                )
                result = await simpleone.create_portal_post(html)
                if result.get("success"):
                    logger.info("Пост о закрытии сбоя %s опубликован на Петлокале", alarm_id)
                else:
                    failed.append("Петлокал")
        except Exception as e:
            logger.warning("Ошибка Петлокал при закрытии сбоя %s: %s", alarm_id, e, exc_info=True)
            failed.append("Петлокал")

    async def _task_channels() -> None:
        text = f"✅ Сбой устранён\n• Проблема: {alarm_copy['issue']}"
        try:
            ok = await send_to_alarm_channels(telegram_bot, text)
            if not ok:
                failed.append("каналы ТГ/MAX")
        except Exception as e:
            logger.warning("Ошибка отправки в каналы при закрытии сбоя %s: %s", alarm_id, e, exc_info=True)
            failed.append("каналы ТГ/MAX")

    await asyncio.gather(_task_max_archive(), _task_scm(), _task_petlocal(), _task_channels())

    del bot_state.active_alarms[alarm_id]
    await bot_state.save_state()

    msg = f"🚨 Сбой {alarm_id} остановлен."
    if failed:
        msg += f"\n⚠️ Частичные сбои: {', '.join(failed)}. Проверьте логи."
    await reply_fn(msg)
    return True


async def stop_maintenance(
    work_id: str,
    telegram_bot: Any,
    reply_fn: ReplyFn,
) -> bool:
    """
    Завершает регламентную работу. Петлокал и каналы выполняются параллельно.
    """
    maint_info = bot_state.active_maintenances.get(work_id)
    if not maint_info:
        await reply_fn("❌ Работа не найдена.")
        return False

    maint_copy = dict(maint_info)
    failed: list[str] = []

    async def _task_petlocal() -> None:
        if not maint_copy.get("publish_petlocal", True):
            return
        try:
            closed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
            async with SimpleOneService() as simpleone:
                html = simpleone.format_maintenance_closed_for_petlocal(
                    work_id=work_id,
                    description=maint_copy.get("description", "не указано"),
                    closed_at=closed_at,
                )
                result = await simpleone.create_portal_post(html)
                if result.get("success"):
                    logger.info("Пост о завершении работы %s опубликован на Петлокале", work_id)
                else:
                    failed.append("Петлокал")
        except Exception as e:
            logger.warning("Ошибка Петлокал при закрытии работы %s: %s", work_id, e, exc_info=True)
            failed.append("Петлокал")

    async def _task_channels() -> None:
        text = f"✅ <b>Работа завершена</b>\n• <b>Описание:</b> {maint_copy['description']}"
        try:
            ok = await send_to_alarm_channels(telegram_bot, text)
            if not ok:
                failed.append("каналы ТГ/MAX")
        except Exception as e:
            logger.warning("Ошибка каналов при закрытии работы %s: %s", work_id, e, exc_info=True)
            failed.append("каналы ТГ/MAX")

    await asyncio.gather(_task_petlocal(), _task_channels())

    del bot_state.active_maintenances[work_id]
    await bot_state.save_state()

    msg = f"🔧 Работа {work_id} остановлена."
    if failed:
        msg += f"\n⚠️ Частичные сбои: {', '.join(failed)}. Проверьте логи."
    await reply_fn(msg)
    return True


def _parse_fix_time(alarm_info: dict, alarm_id: str) -> Optional[datetime]:
    v = alarm_info.get("fix_time")
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            pass
    return None


async def extend_alarm(
    alarm_id: str,
    minutes: int,
    telegram_bot: Any,
    reply_fn: ReplyFn,
) -> bool:
    """
    Продлевает сбой на указанное количество минут.
    Returns: True если сбой найден и продлён.
    """
    alarm = bot_state.active_alarms.get(alarm_id)
    if not alarm:
        await reply_fn("❌ Сбой не найден.")
        return False

    old_end = _parse_fix_time(alarm, alarm_id)
    if not old_end:
        await reply_fn("❌ Некорректное время завершения сбоя.")
        return False

    new_end = old_end + timedelta(minutes=minutes)
    alarm["fix_time"] = new_end.isoformat()
    if "reminder_sent_for" in alarm:
        del alarm["reminder_sent_for"]

    text = (
        f"🔄 <b>Сбой продлён</b>\n"
        f"• <b>Проблема:</b> {alarm['issue']}\n"
        f"• <b>Новое время окончания:</b> {new_end.strftime('%d.%m.%Y %H:%M')}"
    )
    async def _send_channels():
        try:
            if not await send_to_alarm_channels(telegram_bot, text):
                logger.error("Не удалось отправить сообщение о продлении сбоя %s", alarm_id)
        except Exception as e:
            logger.warning("Ошибка каналов при продлении сбоя %s: %s", alarm_id, e, exc_info=True)
    asyncio.create_task(_send_channels())
    await bot_state.save_state()
    await reply_fn(f"✅ Сбой {alarm_id} продлён до {new_end.strftime('%d.%m.%Y %H:%M')}.")
    return True


def _parse_end_time(work_info: dict) -> Optional[datetime]:
    v = work_info.get("end_time") or work_info.get("end")
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            pass
    return None


async def extend_maintenance(
    work_id: str,
    minutes: int,
    telegram_bot: Any,
    reply_fn: ReplyFn,
) -> bool:
    """
    Продлевает регламентную работу на указанное количество минут.
    Returns: True если работа найдена и продлена.
    """
    maint = bot_state.active_maintenances.get(work_id)
    if not maint:
        await reply_fn("❌ Работа не найдена.")
        return False

    old_end = _parse_end_time(maint)
    if not old_end:
        await reply_fn("❌ Некорректное время окончания работы.")
        return False

    new_end = old_end + timedelta(minutes=minutes)
    maint["end_time"] = new_end.isoformat()
    if "end" in maint:
        maint["end"] = new_end.isoformat()
    if "reminder_sent_for" in maint:
        del maint["reminder_sent_for"]

    text = (
        f"🔄 <b>Работа продлена</b>\n"
        f"• <b>Описание:</b> {maint['description']}\n"
        f"• <b>Новое время окончания:</b> {new_end.strftime('%d.%m.%Y %H:%M')}"
    )
    async def _send_channels():
        try:
            if not await send_to_alarm_channels(telegram_bot, text):
                logger.error("Не удалось отправить сообщение о продлении работы %s", work_id)
        except Exception as e:
            logger.warning("Ошибка каналов при продлении работы %s: %s", work_id, e, exc_info=True)
    asyncio.create_task(_send_channels())
    await bot_state.save_state()
    await reply_fn(f"✅ Работа {work_id} продлена до {new_end.strftime('%d.%m.%Y %H:%M')}.")
    return True
