# core/actions.py — остановка и продление событий (MAX)

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, Awaitable, Any, Optional

from bot_state import bot_state
from config import CONFIG, jira_browse_url
from utils.channel_helpers import send_to_alarm_channel
from services.simpleone_service import SimpleOneService
from services.max_archive import process_max_chat_on_alarm_close
from services.max_service import MaxService
from services.alarm_history_service import append_alarm_closed
from utils.jira_close_fa import resolve_jira_key, set_time_end_problem
from utils.bot_time import bot_now_naive

logger = logging.getLogger(__name__)

ReplyFn = Callable[[str], Awaitable[Any]]


async def stop_alarm(
    alarm_id: str,
    reply_fn: ReplyFn,
) -> bool:
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
    jira_key = resolve_jira_key(alarm_id, alarm_info)
    failed: list[str] = []
    closed_at_dt = bot_now_naive()

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
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Архив MAX для %s: %s", alarm_id, e, exc_info=True)
            failed.append("архив MAX→JIRA")

    async def _task_petlocal() -> None:
        if not alarm_copy.get("publish_petlocal", True):
            return
        try:
            closed_at = closed_at_dt.strftime("%d.%m.%Y %H:%M")
            async with SimpleOneService() as simpleone:
                html = simpleone.format_alarm_closed_for_petlocal(
                    alarm_id=alarm_id,
                    issue=alarm_copy.get("issue", "не указано"),
                    closed_at=closed_at,
                )
                result = await simpleone.create_portal_post(html)
                if not result.get("success"):
                    failed.append("Петлокал")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Петлокал %s: %s", alarm_id, e, exc_info=True)
            failed.append("Петлокал")

    async def _task_channels() -> None:
        text = f"✅ Сбой устранён\n• Проблема: {alarm_copy['issue']}"
        if not await send_to_alarm_channel(text):
            failed.append("канал MAX")

    async def _task_jira_time_end() -> None:
        if not jira_key:
            return
        try:
            ok = await set_time_end_problem(jira_key, closed_at_dt)
            if not ok:
                failed.append("Jira TimeEndProblem")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("JIRA TimeEndProblem %s: %s", jira_key, e, exc_info=True)
            failed.append("Jira TimeEndProblem")

    await asyncio.gather(_task_max_archive(), _task_petlocal(), _task_channels(), _task_jira_time_end())

    append_alarm_closed(alarm_id=alarm_id, alarm_info=alarm_copy, closed_at=closed_at_dt)
    del bot_state.active_alarms[alarm_id]
    await bot_state.save_state()

    msg = f"🚨 Сбой {alarm_id} остановлен."
    if failed:
        msg += f"\n⚠️ Частичные сбои: {', '.join(failed)}."
    await reply_fn(msg)
    return True


async def stop_maintenance(
    work_id: str,
    reply_fn: ReplyFn,
) -> bool:
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
            closed_at = bot_now_naive().strftime("%d.%m.%Y %H:%M")
            async with SimpleOneService() as simpleone:
                html = simpleone.format_maintenance_closed_for_petlocal(
                    work_id=work_id,
                    description=maint_copy.get("description", "не указано"),
                    closed_at=closed_at,
                )
                result = await simpleone.create_portal_post(html)
                if not result.get("success"):
                    failed.append("Петлокал")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            failed.append("Петлокал")
            logger.warning("Петлокал %s: %s", work_id, e, exc_info=True)

    async def _task_channels() -> None:
        text = f"✅ Работа завершена\n• Описание: {maint_copy['description']}"
        if not await send_to_alarm_channel(text):
            failed.append("канал MAX")

    await asyncio.gather(_task_petlocal(), _task_channels())

    del bot_state.active_maintenances[work_id]
    await bot_state.save_state()

    msg = f"🔧 Работа {work_id} остановлена."
    if failed:
        msg += f"\n⚠️ Частичные сбои: {', '.join(failed)}."
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
    reply_fn: ReplyFn,
) -> bool:
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
    alarm.pop("reminder_sent_for", None)

    text = (
        f"🔄 Сбой продлён\n"
        f"• Проблема: {alarm['issue']}\n"
        f"• Новое время окончания: {new_end.strftime('%d.%m.%Y %H:%M')}"
    )

    async def _send_channels():
        try:
            await send_to_alarm_channel(text)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Канал при продлении %s: %s", alarm_id, e)

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
    reply_fn: ReplyFn,
) -> bool:
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
    maint.pop("reminder_sent_for", None)

    text = (
        f"🔄 Работа продлена\n"
        f"• Описание: {maint['description']}\n"
        f"• Новое время окончания: {new_end.strftime('%d.%m.%Y %H:%M')}"
    )

    async def _send_channels():
        try:
            await send_to_alarm_channel(text)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Канал при продлении работы %s: %s", work_id, e)

    asyncio.create_task(_send_channels())
    await bot_state.save_state()
    await reply_fn(f"✅ Работа {work_id} продлена до {new_end.strftime('%d.%m.%Y %H:%M')}.")
    return True
