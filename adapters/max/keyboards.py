# adapters/max/keyboards.py — инлайн-клавиатуры для MAX (аналог Telegram)

import logging
from typing import List, Optional, Any

logger = logging.getLogger(__name__)


def _get_services():
    try:
        from config import PROBLEM_SERVICES
        return PROBLEM_SERVICES
    except Exception:
        return []


def _btn(text: str, payload: str) -> Any:
    from maxapi.types import CallbackButton
    return CallbackButton(text=text, payload=payload)


def _pack(rows: List[List[Any]]) -> Optional[List[Any]]:
    """Собирает ряды кнопок в вложение для message.answer(attachments=)."""
    try:
        from maxapi.types.attachments.attachment import ButtonsPayload
        return [ButtonsPayload(buttons=rows).pack()]
    except Exception as e:
        logger.debug("MAX клавиатура не создана: %s", e)
        return None


def main_menu() -> Optional[List[Any]]:
    """Главное меню: Сообщить, Текущие события, Управлять, Помощь."""
    return _pack([
        [_btn("📢 Сообщить", "cmd_report"), _btn("📕 Текущие события", "cmd_events")],
        [_btn("🛂 Управлять", "cmd_manage"), _btn("ℹ️ Помощь", "cmd_help")],
    ])


def message_type_menu() -> Optional[List[Any]]:
    """Выбор типа сообщения: Сбой, Работа, Обычное, Назад."""
    return _pack([
        [_btn("🚨 Сбой", "msg_type_alarm"), _btn("🔧 Работа", "msg_type_maintenance")],
        [_btn("📝 Обычное сообщение", "msg_type_regular")],
        [_btn("◀️ Назад в меню", "cmd_back")],
    ])


def event_list_menu() -> Optional[List[Any]]:
    """События: Сбои, Работы, Обновить, Назад."""
    return _pack([
        [_btn("🚨 Сбои", "events_alarms"), _btn("🔧 Работы", "events_works")],
        [_btn("🔄 Обновить", "events_refresh"), _btn("◀️ Назад в меню", "cmd_back")],
    ])


def manage_type_menu() -> Optional[List[Any]]:
    """Управлять: Сбои, Работы, Назад."""
    return _pack([
        [_btn("🚨 Сбои", "manage_alarms"), _btn("🔧 Работы", "manage_works")],
        [_btn("◀️ Назад в меню", "cmd_back")],
    ])


def action_menu(item_id: str, item_type: str) -> Optional[List[Any]]:
    """Остановить / Продлить / Назад для выбранного события. item_type: alarm | maintenance."""
    prefix = "a" if item_type == "alarm" else "m"
    return _pack([
        [_btn("🛑 Остановить", f"action_stop_{prefix}_{item_id}"), _btn("⏳ Продлить", f"action_extend_{prefix}_{item_id}")],
        [_btn("◀️ Назад", "manage_back")],
    ])


def extend_duration_menu(item_id: str, item_type: str) -> Optional[List[Any]]:
    """Продление: 30 мин, 1 час, Назад."""
    prefix = "a" if item_type == "alarm" else "m"
    return _pack([
        [_btn("➕ 30 мин", f"extend_30_{prefix}_{item_id}"), _btn("➕ 1 час", f"extend_60_{prefix}_{item_id}")],
        [_btn("◀️ Назад", "manage_back")],
    ])


def back_only() -> Optional[List[Any]]:
    """Только кнопка «Назад в меню» (для сценария Сообщить)."""
    return _pack([[_btn("◀️ Назад в меню", "cmd_back")]])


def jira_option_keyboard() -> Optional[List[Any]]:
    """Создать задачу в Jira? (как в Telegram)."""
    return _pack([
        [_btn("✅ Да", "jira_yes"), _btn("❌ Нет", "jira_no")],
        [_btn("◀️ Назад в меню", "cmd_back")],
    ])


def scm_option_keyboard() -> Optional[List[Any]]:
    """Завести тему в SCM? (как в Telegram)."""
    return _pack([
        [_btn("✅ Завести в SCM", "scm_create"), _btn("❌ Не заводить в SCM", "scm_skip")],
        [_btn("◀️ Назад в меню", "cmd_back")],
    ])


def petlocal_option_keyboard() -> Optional[List[Any]]:
    """Публиковать на Петлокале? (как в Telegram) — Да / Нет."""
    return _pack([
        [_btn("✅ Да", "petlocal_publish"), _btn("❌ Нет", "petlocal_skip")],
        [_btn("◀️ Назад в меню", "cmd_back")],
    ])


def confirmation_keyboard() -> Optional[List[Any]]:
    """Подтверждение отправки — Подтвердить / Отмена."""
    return _pack([
        [_btn("✅ Подтвердить", "confirm_send"), _btn("❌ Отмена", "cmd_back")],
    ])


def regular_photo_skip_keyboard() -> Optional[List[Any]]:
    """Приложить картинку к обычному сообщению (в MAX — только кнопка Пропустить)."""
    return _pack([
        [_btn("⏭ Пропустить", "regular_skip_photo")],
        [_btn("◀️ Назад в меню", "cmd_back")],
    ])


# MAX API ограничивает число рядов клавиатуры (errors.maxRows) — размещаем по несколько кнопок в ряд
SERVICES_BUTTONS_PER_ROW = 4


def service_keyboard() -> Optional[List[Any]]:
    """Клавиатура выбора затронутого сервиса (по несколько кнопок в ряд из-за лимита maxRows в MAX)."""
    services = _get_services()
    if not services:
        return back_only()
    rows = []
    for i in range(0, len(services), SERVICES_BUTTONS_PER_ROW):
        chunk = services[i : i + SERVICES_BUTTONS_PER_ROW]
        rows.append([_btn(name, f"svc_{i + j}") for j, name in enumerate(chunk)])
    rows.append([_btn("◀️ Назад в меню", "cmd_back")])
    return _pack(rows)


def alarm_list_keyboard(alarm_items: List[tuple]) -> Optional[List[Any]]:
    """Список сбоёв кнопками. alarm_items: [(alarm_id, issue_short), ...], макс 10."""
    rows = []
    for aid, _short in (alarm_items or [])[:10]:
        rows.append([_btn(f"🚨 {aid}", f"select_a_{aid}")])
    rows.append([_btn("◀️ Назад", "manage_back")])
    return _pack(rows) if rows else _pack([[_btn("◀️ Назад", "manage_back")]])


def maintenance_list_keyboard(work_items: List[tuple]) -> Optional[List[Any]]:
    """Список работ кнопками. work_items: [(work_id, description_short), ...], макс 10."""
    rows = []
    for wid, _short in (work_items or [])[:10]:
        rows.append([_btn(f"🔧 {wid}", f"select_m_{wid}")])
    rows.append([_btn("◀️ Назад", "manage_back")])
    return _pack(rows) if rows else _pack([[_btn("◀️ Назад", "manage_back")]])


def maintenance_time_method_keyboard() -> Optional[List[Any]]:
    """Выбор способа ввода времени работ: спиннеры или текст."""
    return _pack([
        [_btn("🎚️ Спиннеры", "maint_time_spinners"), _btn("✏️ Ввести текстом", "maint_time_manual")],
        [_btn("◀️ Назад в меню", "cmd_back")],
    ])


def create_time_spinner_keyboard_max(
    field_type: str,
    current_value: int,
    step: int,
) -> Optional[List[Any]]:
    """
    Клавиатура спиннера для MAX: ⬆️ / ⬇️, Дальше, Назад, Отмена.
    Payload: spinner_inc_{field}_{val}_{step}, spinner_dec_..., spinner_next, spinner_prev, spinner_cancel.
    """
    inc_p = f"spinner_inc_{field_type}_{current_value}_{step}"
    dec_p = f"spinner_dec_{field_type}_{current_value}_{step}"
    return _pack([
        [_btn("⬆️", inc_p), _btn("⬇️", dec_p)],
        [_btn("✅ Дальше", "spinner_next"), _btn("⏪ Назад", "spinner_prev")],
        [_btn("❌ Отмена", "spinner_cancel")],
    ])
