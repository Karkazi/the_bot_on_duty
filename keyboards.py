#keyboards.py

import logging
from bot_state import bot_state
from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from config import PROBLEM_LEVELS, PROBLEM_SERVICES

logger = logging.getLogger(__name__)


def create_main_keyboard(user_id: int = None) -> ReplyKeyboardMarkup:
    """
    Создает главную клавиатуру.
    
    Args:
        user_id: ID пользователя (для проверки прав MTProto админа)
    """
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup  # Чтобы избежать циклического импорта
    from config import CONFIG

    builder = ReplyKeyboardBuilder()
    builder.add(
        KeyboardButton(text="📢 Сообщить"),
        KeyboardButton(text="🛂 Управлять"),
        KeyboardButton(text="📕 Текущие события"),
        KeyboardButton(text="ℹ️ Помощь")
    )
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def create_message_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🚨 Сбой", callback_data="message_type_alarm"),
        InlineKeyboardButton(text="🔧 Работа", callback_data="message_type_maintenance")
    )
    builder.row(
        InlineKeyboardButton(text="📝 Обычное сообщение", callback_data="message_type_regular")
    )
    return builder.as_markup()


def create_cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
    )
    return builder.as_markup()


def create_yes_no_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data="yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="no")
    )
    return builder.as_markup()


def create_confirmation_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📩 Отправить", callback_data="confirm_send"),
        InlineKeyboardButton(text="🚫 Не отправлять", callback_data="confirm_cancel")
    )
    return builder.as_markup()


# --- Изменённые функции для работы команды управлять---

def create_action_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🛑 Остановить", callback_data="action_stop"),
        InlineKeyboardButton(text="⏳ Продлить", callback_data="action_extend")
    )
    return builder.as_markup()


def create_extension_time_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ 30 мин", callback_data="extend_30_min"),
        InlineKeyboardButton(text="➕ 1 час", callback_data="extend_1_hour")
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Указать вручную", callback_data="extend_manual")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="extend_cancel")
    )
    return builder.as_markup()


def create_alarm_selection_keyboard(alarm_ids=None):
    """
    Создает клавиатуру для выбора аварии.
    
    Оптимизирована для отображения большого количества аварий.
    Если аварий больше 10, можно добавить пагинацию в будущем.
    
    Args:
        alarm_ids: Словарь аварий {alarm_id: alarm_data} или список ID аварий
    
    Returns:
        InlineKeyboardMarkup с кнопками выбора аварий
    """
    builder = InlineKeyboardBuilder()
    
    # Обрабатываем как словарь (если передан словарь) или список
    if alarm_ids is None:
        alarm_ids = {}
    
    # Если передан словарь, конвертируем в список ключей
    if isinstance(alarm_ids, dict):
        alarm_items = list(alarm_ids.items())
    else:
        # Если передан список, создаем словарь из bot_state
        alarm_items = [(aid, bot_state.active_alarms.get(aid)) for aid in alarm_ids if aid in bot_state.active_alarms]
    
    if not alarm_items:
        builder.row(InlineKeyboardButton(text="Нет активных сбоев", callback_data="select_no_alarms"))
    else:
        # Ограничиваем количество кнопок для удобства (максимум 10)
        display_items = alarm_items[:10]
        for alarm_id, alarm in display_items:
            if not alarm:
                continue
            btn_text = f"{alarm_id}: {alarm.get('issue', 'Без описания')[:20]}..."
            builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"select_alarm_{alarm_id}"))
        
        # Если аварий больше 10, показываем предупреждение
        if len(alarm_items) > 10:
            builder.row(InlineKeyboardButton(
                text=f"⚠️ Показано 10 из {len(alarm_items)}",
                callback_data="select_info"
            ))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="select_cancel"))
    return builder.as_markup()


def create_stop_type_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🚨 Сбой 🚨", callback_data="stop_type_alarm"),
        InlineKeyboardButton(text="🔧 Работа 🔧", callback_data="stop_type_maintenance")
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()


def create_maintenance_selection_keyboard(maintenances=None):
    """
    Создает клавиатуру для выбора регламентной работы.
    
    Оптимизирована для отображения большого количества работ.
    
    Args:
        maintenances: Словарь работ {work_id: work_data} или None
    
    Returns:
        InlineKeyboardMarkup с кнопками выбора работ
    """
    builder = InlineKeyboardBuilder()
    
    # Обрабатываем None или пустой словарь
    if maintenances is None:
        maintenances = {}
    
    # Убеждаемся, что это словарь
    if not isinstance(maintenances, dict):
        logger.warning(f"create_maintenance_selection_keyboard получил не словарь: {type(maintenances)}")
        maintenances = {}
    
    work_items = list(maintenances.items())
    
    if not work_items:
        builder.row(InlineKeyboardButton(text="Нет активных работ", callback_data="select_no_maintenances"))
    else:
        # Ограничиваем количество кнопок для удобства (максимум 10)
        display_items = work_items[:10]
        
        for work_id, data in display_items:
            if not data or not isinstance(data, dict):
                continue
            owner_info = f" (от {data['user_id']})" if 'user_id' in data else ""
            description = data.get('description', 'Без описания')
            if not isinstance(description, str):
                description = str(description)
            btn_text = f"{work_id}: {description[:20]}...{owner_info}"
            builder.row(
                InlineKeyboardButton(
                    text=btn_text,
                    callback_data=f"select_maintenance_{work_id}"
                )
            )
        
        # Если работ больше 10, показываем предупреждение
        if len(work_items) > 10:
            builder.row(InlineKeyboardButton(
                text=f"⚠️ Показано 10 из {len(work_items)}",
                callback_data="select_info"
            ))
    
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="select_cancel"))
    return builder.as_markup()


def create_reminder_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, продлеваем", callback_data="reminder_extend"),
        InlineKeyboardButton(text="❌ Нет, останавливаем", callback_data="reminder_stop")
    )
    return builder.as_markup()


def create_maintenance_reminder_keyboard():
    """Создает клавиатуру для напоминаний о работах."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏳ Продлить", callback_data="reminder_extend_maintenance"),
        InlineKeyboardButton(text="✅ Завершить", callback_data="reminder_stop_maintenance")
    )
    return builder.as_markup()


def create_event_list_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🚨 Сбои", callback_data="show_alarms")
    builder.button(text="🔧 Работы", callback_data="show_maintenances")
    builder.button(text="❌ Закрыть", callback_data="close_selection")
    builder.adjust(1)
    return builder.as_markup()


def create_level_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора уровня проблемы."""
    builder = InlineKeyboardBuilder()
    for i, level in enumerate(PROBLEM_LEVELS):
        builder.button(text=level, callback_data=f"lvl_{i}")
    builder.button(text="Отмена", callback_data="cancel")
    builder.adjust(1)  # Размещаем кнопки в один столбец
    return builder.as_markup()


def create_service_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора сервиса."""
    builder = InlineKeyboardBuilder()
    for i, service in enumerate(PROBLEM_SERVICES):
        builder.button(text=service, callback_data=f"svc_{i}")
    builder.button(text="Отмена", callback_data="cancel")
    builder.adjust(1)  # Размещаем кнопки в один столбец
    return builder.as_markup()


def create_jira_option_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора создания задачи в Jira."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Создать задачу в Jira", callback_data="jira_create"),
        InlineKeyboardButton(text="❌ Без задачи в Jira", callback_data="jira_skip")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
    )
    return builder.as_markup()


def create_scm_option_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора создания темы в SCM канале."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Завести в SCM", callback_data="scm_create"),
        InlineKeyboardButton(text="❌ Не заводить в SCM", callback_data="scm_skip")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
    )
    return builder.as_markup()


def create_refresh_keyboard(current_page: int = 0, total_pages: int = 1) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if total_pages and total_pages > 1:
        row = []
        if current_page > 0:
            row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="page_prev"))
        if current_page < total_pages - 1:
            row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data="page_next"))
        if row:
            builder.row(*row)

    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_selection"),
        InlineKeyboardButton(text="❌ Закрыть", callback_data="close_selection")
    )
    return builder.as_markup()


# --- Клавиатуры календаря для выбора даты ---
def create_month_keyboard(year: int, field_prefix: str = "start") -> InlineKeyboardMarkup:
    """Клавиатура выбора месяца"""
    builder = InlineKeyboardBuilder()
    months = [
        ("Янв", 1), ("Фев", 2), ("Мар", 3), ("Апр", 4),
        ("Май", 5), ("Июн", 6), ("Июл", 7), ("Авг", 8),
        ("Сен", 9), ("Окт", 10), ("Ноя", 11), ("Дек", 12)
    ]
    for i in range(0, len(months), 3):
        row = [InlineKeyboardButton(text=m[0], callback_data=f"cal_month_{field_prefix}_{year}_{m[1]}") 
               for m in months[i:i+3]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()


def create_day_keyboard(year: int, month: int, field_prefix: str = "start") -> InlineKeyboardMarkup:
    """Клавиатура выбора дня"""
    from calendar import monthrange
    days_in_month = monthrange(year, month)[1]
    builder = InlineKeyboardBuilder()
    
    # Создаем кнопки для дней месяца (по 7 в ряд для удобства)
    for week_start in range(1, days_in_month + 1, 7):
        week_days = []
        for day in range(week_start, min(week_start + 7, days_in_month + 1)):
            week_days.append(InlineKeyboardButton(
                text=str(day),
                callback_data=f"cal_day_{field_prefix}_{year}_{month}_{day}"
            ))
        if week_days:
            builder.row(*week_days)
    
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()


def create_hour_keyboard(field_prefix: str = "start") -> InlineKeyboardMarkup:
    """Клавиатура выбора часа (0-23)"""
    builder = InlineKeyboardBuilder()
    for i in range(0, 24, 4):
        row = [InlineKeyboardButton(text=f"{h:02d}", callback_data=f"cal_hour_{field_prefix}_{h}") 
               for h in range(i, min(i+4, 24))]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()


def create_minute_keyboard(field_prefix: str = "start") -> InlineKeyboardMarkup:
    """Клавиатура выбора минуты (0, 15, 30, 45)"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="00", callback_data=f"cal_minute_{field_prefix}_0"),
        InlineKeyboardButton(text="15", callback_data=f"cal_minute_{field_prefix}_15"),
        InlineKeyboardButton(text="30", callback_data=f"cal_minute_{field_prefix}_30"),
        InlineKeyboardButton(text="45", callback_data=f"cal_minute_{field_prefix}_45")
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()


# ========================
# 🎚️ SPINNERS / СЛАЙДЕРЫ
# ========================

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