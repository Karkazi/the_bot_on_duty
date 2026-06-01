# Ежедневная сводка регламентных работ из Confluence (10:00 / 18:00)

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

from bot_state import bot_state
from config import CONFIG
from domain.constants import DATETIME_FORMAT
from services.confluence_service import (
    fetch_page_storage,
    get_confluence_calendar_page_ids,
    parse_works_table,
)
from services.max_service import MaxService
from utils.bot_time import bot_now_naive

logger = logging.getLogger(__name__)

DIGEST_CHECK_INTERVAL_SEC = 60


def work_overlaps_calendar_day(work: dict, day: date) -> bool:
    """Работа пересекает календарные сутки day (00:00–23:59, BOT_TIMEZONE)."""
    start = work.get("start_time")
    end = work.get("end_time")
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return False
    day_start = datetime.combine(day, time.min)
    day_end = datetime.combine(day, time.max)
    return start <= day_end and end >= day_start


def filter_works_for_day(rows: List[dict], day: date) -> List[dict]:
    matched = [r for r in rows if work_overlaps_calendar_day(r, day)]
    matched.sort(key=lambda r: r.get("start_time") or datetime.min)
    return matched


def format_daily_digest(works: List[dict], day: date) -> str:
    date_label = day.strftime("%d.%m.%Y")
    if not works:
        return f"📅 На {date_label} работ в календаре нет."

    lines = [f"📅 Регламентные работы на {date_label}", ""]
    for i, row in enumerate(works, 1):
        desc = row.get("description") or "—"
        start_s = row.get("start_time_str") or "—"
        end_s = row.get("end_time_str") or "—"
        services = row.get("unavailable_services") or "—"
        owner = row.get("owner") or "—"
        inform_s = row.get("inform_at_str") or "—"
        lines.append(f"{i}. {desc}")
        lines.append(f"   {start_s} — {end_s} | {services} | {owner}")
        lines.append(f"   Информирование: {inform_s}")
        if i < len(works):
            lines.append("")
    return "\n".join(lines)


def _confluence_configured() -> bool:
    conf = CONFIG.get("CONFLUENCE", {}) or {}
    return bool(
        conf.get("LOGIN_URL")
        and (conf.get("TOKEN") or (conf.get("USERNAME") and conf.get("PASSWORD")))
    )


async def get_today_calendar_digest_text(day: Optional[date] = None) -> str:
    """Текст сводки работ на день (тот же формат, что в 10:00 / 18:00)."""
    day = day or bot_now_naive().date()
    if not _confluence_configured():
        return "⚠️ Confluence не настроен — календарь недоступен."
    try:
        rows = await load_all_calendar_rows()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("[DIGEST] Ошибка загрузки календаря: %s", e, exc_info=True)
        return "⚠️ Не удалось загрузить календарь. Попробуйте позже."
    works = filter_works_for_day(rows, day)
    return format_daily_digest(works, day)


async def load_all_calendar_rows() -> List[dict]:
    page_ids = await get_confluence_calendar_page_ids()
    seen: set[str] = set()
    rows: List[dict] = []
    for page_id in page_ids:
        storage = await fetch_page_storage(page_id)
        if not storage:
            continue
        for row in parse_works_table(storage):
            wid = row.get("work_id")
            if not wid or wid in seen:
                continue
            seen.add(wid)
            rows.append(row)
    return rows


def _digest_slot_key(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _current_slot(now: datetime, digest_times: List[Tuple[int, int]]) -> Optional[str]:
    for hour, minute in digest_times:
        if now.hour == hour and now.minute == minute:
            return _digest_slot_key(hour, minute)
    return None


def _prune_old_digest_state(max_days: int = 14) -> None:
    cutoff = (bot_now_naive().date() - timedelta(days=max_days)).isoformat()
    stale = [k for k in bot_state.calendar_digest_sent if k < cutoff]
    for k in stale:
        bot_state.calendar_digest_sent.pop(k, None)


async def send_digest_for_slot(slot: str, day: date) -> bool:
    """Формирует и отправляет сводку. True — отправлено хотя бы одному админу."""
    calendar_admin_ids = (CONFIG.get("MAX") or {}).get("CALENDAR_ADMIN_IDS") or []
    if not calendar_admin_ids:
        return False

    max_svc = MaxService()
    if not max_svc.is_configured():
        logger.warning("[DIGEST] MAX не настроен, сводка %s не отправлена", slot)
        return False

    text = await get_today_calendar_digest_text(day)
    if text.startswith("⚠️"):
        logger.warning("[DIGEST] Сводка %s не отправлена: %s", slot, text)
        return False
    sent_any = False
    for uid in calendar_admin_ids:
        try:
            ok = await max_svc.send_message_to_user(int(uid), text, strip_html=True)
            if ok:
                sent_any = True
                logger.info("[DIGEST] Сводка %s на %s → MAX user_id=%s", slot, day.isoformat(), uid)
            else:
                logger.warning("[DIGEST] Не удалось отправить сводку user_id=%s", uid)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[DIGEST] Ошибка отправки user_id=%s: %s", uid, e, exc_info=True)

    if sent_any:
        day_key = day.isoformat()
        slots = bot_state.calendar_digest_sent.setdefault(day_key, [])
        if slot not in slots:
            slots.append(slot)
        _prune_old_digest_state()
        await bot_state.save_state()
    return sent_any


async def run_calendar_digest_scheduler() -> None:
    """Раз в минуту проверяет слоты CALENDAR_DIGEST_TIMES и шлёт сводку дежурным."""
    cal_cfg = CONFIG.get("CALENDAR") or {}
    if not cal_cfg.get("DIGEST_ENABLED", True):
        logger.info("[DIGEST] Ежедневная сводка отключена (CALENDAR_DIGEST_ENABLED=0)")
        return

    digest_times: List[Tuple[int, int]] = cal_cfg.get("DIGEST_TIMES") or [(10, 0), (18, 0)]
    times_label = ", ".join(_digest_slot_key(h, m) for h, m in digest_times)
    logger.info("[DIGEST] Планировщик сводки запущен (слоты: %s)", times_label)

    while True:
        try:
            now = bot_now_naive()
            slot = _current_slot(now, digest_times)
            if slot:
                day_key = now.date().isoformat()
                if slot not in bot_state.calendar_digest_sent.get(day_key, []):
                    await send_digest_for_slot(slot, now.date())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[DIGEST] Ошибка планировщика: %s", e, exc_info=True)
        await asyncio.sleep(DIGEST_CHECK_INTERVAL_SEC)
