"""
Очистка устаревших записей в state после перезапуска и перед фоновыми задачами.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Tuple

from utils.bot_time import bot_now_naive

if TYPE_CHECKING:
    from bot_state import BotState

logger = logging.getLogger(__name__)

# После inform_at ещё можно уведомить; дальше — «пропущено», без спама при рестарте
INFORM_NOTIFY_GRACE = timedelta(hours=2)


def prune_stale_state(bot_state: "BotState", now: datetime | None = None) -> bool:
    """
    Убирает завершённые работы из active_maintenances и закрывает просроченные
    записи Confluence без повторных уведомлений.

    Returns:
        True, если state изменился и нужен save.
    """
    now = now or bot_now_naive()
    changed = False

    stale_work_ids = []
    for work_id, work in bot_state.active_maintenances.items():
        end = work.get("end_time") or work.get("end")
        if isinstance(end, datetime) and end <= now:
            stale_work_ids.append(work_id)
    for work_id in stale_work_ids:
        del bot_state.active_maintenances[work_id]
        changed = True
        logger.info("[CLEANUP] Удалена завершённая работа %s из active_maintenances", work_id)

    stale_alarm_ids = []
    for alarm_id, alarm in bot_state.active_alarms.items():
        fix = alarm.get("fix_time")
        if isinstance(fix, datetime) and fix <= now:
            stale_alarm_ids.append(alarm_id)
    for alarm_id in stale_alarm_ids:
        del bot_state.active_alarms[alarm_id]
        changed = True
        logger.info("[CLEANUP] Удалён завершённый сбой %s из active_alarms", alarm_id)

    for work_id, entry in list(bot_state.known_maintenances_from_confluence.items()):
        status = (entry.get("status") or "").strip()
        end_time = entry.get("end_time")
        inform_at = entry.get("inform_at")

        if isinstance(end_time, datetime) and end_time <= now:
            if status != "expired":
                entry["status"] = "expired"
                changed = True
                logger.info("[CLEANUP] Confluence %s → expired (работа завершена)", work_id)
            continue

        if status in ("waiting_inform_time", "scheduled") and isinstance(inform_at, datetime):
            if now > inform_at + INFORM_NOTIFY_GRACE:
                entry["status"] = "inform_missed"
                changed = True
                logger.info(
                    "[CLEANUP] Confluence %s → inform_missed (inform_at=%s, без уведомления)",
                    work_id,
                    inform_at.isoformat(),
                )

    if changed:
        logger.info("[CLEANUP] Состояние очищено от устаревших записей")
    return changed


def should_skip_confluence_notify(entry: dict, now: datetime | None = None) -> Tuple[bool, str | None]:
    """
    Проверка перед notify_admins_about_work.
    Returns:
        (skip, new_status) — если skip, new_status выставить в entry.
    """
    now = now or bot_now_naive()
    inform_at = entry.get("inform_at")
    end_time = entry.get("end_time")

    if isinstance(end_time, datetime) and end_time <= now:
        return True, "expired"

    if isinstance(inform_at, datetime) and now > inform_at + INFORM_NOTIFY_GRACE:
        return True, "inform_missed"

    return False, None
