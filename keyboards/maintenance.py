"""
Клавиатуры для работы с регламентными работами (maintenance).
Содержит клавиатуры выбора времени работ, спиннеры и т.д.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def create_maintenance_time_selection_keyboard() -> InlineKeyboardMarkup:
    """Выбор способа ввода времени регламентных работ"""
    builder = InlineKeyboardBuilder()
    
    builder.row(InlineKeyboardButton(
        text="🎚️ Спиннеры (быстро)",
        callback_data="maint_method_spinners"
    ))
    
    builder.row(InlineKeyboardButton(
        text="📅 Календарь",
        callback_data="maint_method_calendar"
    ))
    
    builder.row(InlineKeyboardButton(
        text="✏️ Указать вручную",
        callback_data="maint_method_manual"
    ))
    
    builder.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="cancel_action"
    ))
    
    return builder.as_markup()


def create_maintenance_extend_time_selection_keyboard() -> InlineKeyboardMarkup:
    """Выбор способа ввода нового времени окончания при продлении работ"""
    builder = InlineKeyboardBuilder()
    
    builder.row(InlineKeyboardButton(
        text="🎚️ Спиннеры (быстро)",
        callback_data="maint_extend_spinners"
    ))
    
    builder.row(InlineKeyboardButton(
        text="📅 Календарь",
        callback_data="maint_extend_calendar"
    ))
    
    builder.row(InlineKeyboardButton(
        text="✏️ Указать вручную",
        callback_data="maint_extend_text"
    ))
    
    builder.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="cancel_action"
    ))
    
    return builder.as_markup()


def create_time_spinner_keyboard(
    field_type: str,
    current_value: int,
    label: str,
    min_val: int,
    max_val: int,
    step: int = 1
) -> InlineKeyboardMarkup:
    """
    Создает спиннер для выбора времени
    
    Args:
        field_type: Тип поля ("hour_start", "minute_start", "hour_end", "minute_end", "date")
        current_value: Текущее значение
        label: Человеческое название
        min_val: Минимальное значение
        max_val: Максимальное значение
        step: Шаг изменения (1 для часов, 15 для минут)
    
    Returns:
        InlineKeyboardMarkup с кнопками спиннера
    """
    builder = InlineKeyboardBuilder()
    
    # Форматируем отображение значения
    from domain.constants import MAINTENANCE_TIME_SPINNER_CONFIG
    from datetime import datetime
    
    config = MAINTENANCE_TIME_SPINNER_CONFIG.get(field_type, {})
    format_func = config.get("format", lambda v: str(v))
    
    if field_type == "date":
        display_text = format_func(current_value, datetime.now())
    else:
        display_text = format_func(current_value)
    
    # Кнопки управления
    builder.row(
        InlineKeyboardButton(text="⬆️", callback_data=f"spinner_inc_{field_type}_{current_value}_{step}"),
        InlineKeyboardButton(text=display_text, callback_data="spinner_display"),
        InlineKeyboardButton(text="⬇️", callback_data=f"spinner_dec_{field_type}_{current_value}_{step}")
    )
    
    # Информационная строка (мин - макс)
    builder.row(
        InlineKeyboardButton(
            text=f"📊 {min_val} ← → {max_val}",
            callback_data="spinner_info"
        )
    )
    
    # Кнопки действия
    builder.row(
        InlineKeyboardButton(text="✅ Дальше", callback_data="spinner_next_step"),
        InlineKeyboardButton(text="⏪ Назад", callback_data="spinner_prev_step")
    )
    
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="spinner_cancel")
    )
    
    return builder.as_markup()


def create_spinner_progress_bar(current_step: int, total_steps: int = 5) -> str:
    """
    Создает визуальную полоску прогресса
    
    Args:
        current_step: Текущий шаг (1-5)
        total_steps: Всего шагов (по умолчанию 5)
    
    Returns:
        Строка с полоской прогресса
    
    Пример:
        ▓▓▓░░ 3/5 - Время начала (минуты)
    """
    filled = "▓" * current_step
    empty = "░" * (total_steps - current_step)
    return f"{filled}{empty} {current_step}/{total_steps}"


def create_extend_time_spinner_keyboard(
    field_type: str,
    current_value: int,
    label: str,
    min_val: int,
    max_val: int,
    step: int = 1
) -> InlineKeyboardMarkup:
    """
    Создает спиннер для выбора времени окончания при продлении работ
    Упрощенная версия - только час и минута
    """
    builder = InlineKeyboardBuilder()
    
    # Форматируем отображение значения
    from domain.constants import MAINTENANCE_TIME_SPINNER_CONFIG
    config = MAINTENANCE_TIME_SPINNER_CONFIG.get(field_type, {})
    format_func = config.get("format", lambda v: str(v))
    display_text = format_func(current_value)
    
    # Кнопки управления
    builder.row(
        InlineKeyboardButton(text="⬆️", callback_data=f"extend_spinner_inc_{field_type}_{current_value}_{step}"),
        InlineKeyboardButton(text=display_text, callback_data="extend_spinner_display"),
        InlineKeyboardButton(text="⬇️", callback_data=f"extend_spinner_dec_{field_type}_{current_value}_{step}")
    )
    
    # Информационная строка (мин - макс)
    builder.row(
        InlineKeyboardButton(
            text=f"📊 {min_val} ← → {max_val}",
            callback_data="extend_spinner_info"
        )
    )
    
    # Кнопки действия
    builder.row(
        InlineKeyboardButton(text="✅ Дальше", callback_data="extend_spinner_next_step"),
        InlineKeyboardButton(text="⏪ Назад", callback_data="extend_spinner_prev_step")
    )
    
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="extend_spinner_cancel")
    )
    
    return builder.as_markup()
