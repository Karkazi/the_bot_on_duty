# core/events.py — получение текста списка активных событий (канал-агностично)

import logging
from datetime import datetime
from typing import Tuple, Optional

from bot_state import bot_state

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 5


def _safe_fix_time(alarm_info: dict, alarm_id: str) -> str:
    v = alarm_info.get("fix_time")
    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y %H:%M")
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v).strftime("%d.%m.%Y %H:%M")
        except Exception as e:
            logger.warning(f"Ошибка форматирования времени сбоя {alarm_id}: {e}")
    return "неизвестно"


def _safe_time(v, label: str) -> str:
    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y %H:%M")
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v).strftime("%d.%m.%Y %H:%M")
        except Exception:
            pass
    return "неизвестно"


def get_active_events_text(
    view: str,
    page: int = 0,
    html: bool = True,
) -> Tuple[str, Optional[int]]:
    """
    Возвращает текст списка активных сбоёв или работ и общее число страниц.

    view: "alarms" | "maintenances"
    page: номер страницы (0-based).
    html: использовать ли теги <b>/<code> (для MAX можно False и потом strip).

    Returns:
        (text, total_pages). total_pages None если список пуст.
    """
    if view == "alarms":
        alarms = bot_state.active_alarms
        items = list(alarms.items())
        if not items:
            return "🚨 Нет активных сбоёв.", None
        start = page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_items = items[start:end]
        prefix = "<b>🚨 Активные сбои:</b>\n\n" if html else "🚨 Активные сбои:\n\n"
        lines = []
        for alarm_id, alarm_info in page_items:
            fix_time = _safe_fix_time(alarm_info, alarm_id)
            author = alarm_info.get("user_id", "Неизвестен")
            code = f"<code>{alarm_id}</code>" if html else alarm_id
            lines.append(
                f"• {code}\n  👤 Автор: {author}\n  🕒 Исправим до: {fix_time}\n  🔧 Проблема: {alarm_info.get('issue', '—')}\n"
            )
        text = prefix + "\n".join(lines)
        total_pages = (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        return text, total_pages

    if view == "maintenances":
        maintenances = bot_state.active_maintenances
        items = list(maintenances.items())
        if not items:
            return "🔧 Нет активных работ.", None
        start = page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_items = items[start:end]
        prefix = "<b>🔧 Активные работы:</b>\n\n" if html else "🔧 Активные работы:\n\n"
        lines = []
        for work_id, work_info in page_items:
            start_time = _safe_time(work_info.get("start_time"), work_id)
            end_time = _safe_time(work_info.get("end_time"), work_id)
            description = work_info.get("description", "Нет описания")
            author = work_info.get("user_id", "Неизвестен")
            code = f"<code>{work_id}</code>" if html else work_id
            lines.append(
                f"• {code}\n  👤 Автор: {author}\n  ⏰ Время: {start_time} — {end_time}\n  📝 Описание: {description}\n"
            )
        text = prefix + "\n".join(lines)
        total_pages = (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        return text, total_pages

    return "Укажите: сбои или работы.", None
