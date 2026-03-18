# Фоновая проверка календаря Confluence и уведомление MAX_CALENDAR_ADMIN_IDS о новых работах

import asyncio
import logging
from datetime import datetime

from config import CONFIG
from bot_state import bot_state
from services.confluence_service import (
    fetch_page_storage,
    get_confluence_page_id,
    parse_works_table,
)
from services.max_service import MaxService
from adapters.max.keyboards import confluence_notify_attachment_tokens

logger = logging.getLogger(__name__)

CONFLUENCE_CHECK_INTERVAL_SEC = 10


def _format_calendar_notification(row: dict) -> str:
    """Текст уведомления дежурному: заголовок + описание, время, ответственный, оповещения."""
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
    """
    Отправляет уведомление MAX_CALENDAR_ADMIN_IDS о новой работе в календаре.
    Используется как фоновой задачей, так и при ручном добавлении записи через бота.
    """
    max_cfg = CONFIG.get("MAX", {}) or {}
    calendar_admin_ids = max_cfg.get("CALENDAR_ADMIN_IDS") or []
    if not calendar_admin_ids:
        return
    max_svc = MaxService()
    if not max_svc.is_configured():
        return

    notify_raw = (row.get("notify") or "").strip()
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
        except Exception as e:
            logger.warning("[CONF_MAINT] Ошибка отправки в MAX user_id=%s: %s", uid, e, exc_info=True)


async def check_confluence_maintenances(bot) -> None:
    """
    Раз в CONFLUENCE_CHECK_INTERVAL_SEC секунд проверяет страницу календаря Confluence,
    находит новые работы с заполненным «Оповещения» и шлёт запрос в MAX админам (MAX_CALENDAR_ADMIN_IDS).
    """
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

    page_id = get_confluence_page_id()
    logger.info("[CONF_MAINT] Запущена проверка календаря Confluence (pageId=%s) каждые %s с", page_id, CONFLUENCE_CHECK_INTERVAL_SEC)

    while True:
        try:
            now = datetime.now()
            storage = await fetch_page_storage(page_id)
            if not storage:
                await asyncio.sleep(CONFLUENCE_CHECK_INTERVAL_SEC)
                continue

            rows = parse_works_table(storage)
            known = bot_state.known_maintenances_from_confluence

            for row in rows:
                if not (row.get("notify") or "").strip():
                    continue
                if row["work_id"] in known:
                    continue
                # Не трогаем работы, где окончание уже прошло
                if row["end_time"] <= now:
                    continue

                # Новая работа: сохраняем и уведомляем админов
                notify_raw = (row.get("notify") or "").strip()
                notify_lower = notify_raw.lower()
                no_notify = notify_lower in ("нет", "no", "none", "-")

                known[row["work_id"]] = {
                    **row,
                    "status": "no_notify" if no_notify else "pending_decision",
                }

                await notify_admins_about_work(row)

                await bot_state.save_state()
                break  # по одной новой работе за цикл, остальные подхватим в следующих итерациях
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[CONF_MAINT] Ошибка в цикле проверки Confluence: %s", e, exc_info=True)

        await asyncio.sleep(CONFLUENCE_CHECK_INTERVAL_SEC)
