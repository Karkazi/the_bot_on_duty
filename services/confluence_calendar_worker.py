# Фоновая проверка календаря Confluence и уведомление MAX_CALENDAR_ADMIN_IDS

import asyncio
import logging

from config import CONFIG
from bot_state import bot_state
from services.confluence_service import (
    fetch_page_storage,
    get_confluence_calendar_page_ids,
    parse_works_table,
)
from services.max_service import MaxService
from utils.bot_time import bot_now_naive
from adapters.max.keyboards import confluence_notify_attachment_tokens
from services.state_cleanup import should_skip_confluence_notify

logger = logging.getLogger(__name__)

CONFLUENCE_CHECK_INTERVAL_SEC = 10


def _format_calendar_notification(row: dict) -> str:
    lines = [
        "🔔 Запланированы новые регламентные работы.",
        "",
        f"• Описание: {row.get('description', '—')}",
        f"• Начало: {row.get('start_time_str', '—')}",
        f"• Конец: {row.get('end_time_str', '—')}",
        f"• Недоступно: {row.get('unavailable_services', '—')}",
        f"• Ответственный: {row.get('owner') or '—'}",
        f"• Оповещения: {row.get('notify') or '—'}",
    ]
    return "\n".join(lines)


async def notify_admins_about_work(row: dict) -> None:
    max_cfg = CONFIG.get("MAX", {}) or {}
    calendar_admin_ids = max_cfg.get("CALENDAR_ADMIN_IDS") or []
    if not calendar_admin_ids:
        return
    max_svc = MaxService()
    if not max_svc.is_configured():
        return

    notify_raw = (row.get("notify") or "").strip()
    if not notify_raw:
        return
    notify_lower = notify_raw.lower()
    no_notify = notify_lower in ("нет", "no", "none", "-")

    text = _format_calendar_notification(row)
    att = None if no_notify else confluence_notify_attachment_tokens(row["work_id"])

    for uid in calendar_admin_ids:
        try:
            ok = await max_svc.send_message_to_user(int(uid), text, attachment_tokens=att, strip_html=True)
            if ok:
                logger.info("[CONF_MAINT] Уведомление о работе %s отправлено в MAX user_id=%s", row["work_id"], uid)
            else:
                logger.warning("[CONF_MAINT] Не удалось отправить в MAX user_id=%s", uid)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[CONF_MAINT] Ошибка отправки в MAX user_id=%s: %s", uid, e, exc_info=True)


async def check_confluence_maintenances() -> None:
    max_cfg = CONFIG.get("MAX", {}) or {}
    calendar_admin_ids = max_cfg.get("CALENDAR_ADMIN_IDS") or []
    if not calendar_admin_ids:
        logger.debug("[CONF_MAINT] MAX_CALENDAR_ADMIN_IDS не заданы, задача не запускается")
        return

    conf = CONFIG.get("CONFLUENCE", {}) or {}
    if not (conf.get("LOGIN_URL") and (conf.get("TOKEN") or (conf.get("USERNAME") and conf.get("PASSWORD")))):
        logger.debug("[CONF_MAINT] Confluence не настроен, задача не запускается")
        return

    max_svc = MaxService()
    if not max_svc.is_configured():
        logger.debug("[CONF_MAINT] MAX не настроен, задача не запускается")
        return

    refresh_every_iterations = 60
    iteration = 0
    page_ids = await get_confluence_calendar_page_ids()
    logger.info(
        "[CONF_MAINT] Запущена проверка календаря Confluence (pages=%s) каждые %s с",
        len(page_ids),
        CONFLUENCE_CHECK_INTERVAL_SEC,
    )

    while True:
        try:
            now = bot_now_naive()
            known = bot_state.known_maintenances_from_confluence

            iteration += 1
            if (iteration % refresh_every_iterations) == 0:
                page_ids = await get_confluence_calendar_page_ids()
                logger.info("[CONF_MAINT] Обновлён список календарных страниц. pages=%s", len(page_ids))

            changed = False

            for page_id in page_ids:
                storage = await fetch_page_storage(page_id)
                if not storage:
                    continue

                rows = parse_works_table(storage)

                for row in rows:
                    if row.get("end_time") and row["end_time"] <= now:
                        continue

                    inform_at = row.get("inform_at")
                    notify_raw = (row.get("notify") or "").strip()
                    if not notify_raw:
                        continue
                    if not inform_at or inform_at <= now:
                        continue

                    work_id = row["work_id"]
                    if work_id in known:
                        entry = known[work_id]
                        status = (entry.get("status") or "").strip()
                        if status in ("pending_decision", "waiting_inform_time", "skipped_by_admin"):
                            continue
                        entry.update(row)
                        entry["status"] = "waiting_inform_time"
                        changed = True
                        continue

                    known[work_id] = {**row, "status": "waiting_inform_time"}
                    changed = True
                    continue

            for work_id, entry in list(known.items()):
                status = (entry.get("status") or "").strip()
                if status not in ("waiting_inform_time", "scheduled"):
                    continue
                notify_raw = (entry.get("notify") or "").strip()
                if not notify_raw:
                    entry["status"] = "no_notify"
                    changed = True
                    continue

                end_time = entry.get("end_time")
                if end_time and end_time <= now:
                    entry["status"] = "expired"
                    changed = True
                    continue

                inform_at = entry.get("inform_at")
                if not inform_at or now < inform_at:
                    continue

                skip, new_status = should_skip_confluence_notify(entry, now)
                if skip:
                    if new_status:
                        entry["status"] = new_status
                        changed = True
                    continue

                entry["status"] = "pending_decision"
                await notify_admins_about_work(entry)
                entry["informed_at"] = now.isoformat()
                changed = True

            if changed:
                await bot_state.save_state()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[CONF_MAINT] Ошибка в цикле проверки Confluence: %s", e, exc_info=True)

        await asyncio.sleep(CONFLUENCE_CHECK_INTERVAL_SEC)
