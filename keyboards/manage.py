"""
Клавиатуры для управления событиями (manage).
Содержит клавиатуры для остановки, продления, выбора событий и т.д.
"""
import logging
from bot_state import bot_state
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

logger = logging.getLogger(__name__)


def create_action_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора действия (остановить/продлить/отмена)"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🛑 Остановить", callback_data="action_stop"),
        InlineKeyboardButton(text="⏳ Продлить", callback_data="action_extend")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="action_cancel")
    )
    return builder.as_markup()


def create_extension_time_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора времени продления"""
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


def create_alarm_selection_keyboard(alarm_ids=None) -> InlineKeyboardMarkup:
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


def create_maintenance_selection_keyboard(maintenances=None) -> InlineKeyboardMarkup:
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
            description = data.get('description', 'Без описания')
            if not isinstance(description, str):
                description = str(description)
            btn_text = f"{work_id}: {description[:20]}..."
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


def create_stop_type_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора типа события для остановки"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🚨 Сбой 🚨", callback_data="stop_type_alarm"),
        InlineKeyboardButton(text="🔧 Работа 🔧", callback_data="stop_type_maintenance")
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()


def create_reminder_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для напоминаний об авариях"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, продлеваем", callback_data="reminder_extend"),
        InlineKeyboardButton(text="❌ Нет, останавливаем", callback_data="reminder_stop")
    )
    return builder.as_markup()


def create_maintenance_reminder_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для напоминаний о работах"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏳ Продлить", callback_data="reminder_extend_maintenance"),
        InlineKeyboardButton(text="✅ Завершить", callback_data="reminder_stop_maintenance")
    )
    return builder.as_markup()


def create_event_list_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора типа событий для просмотра"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🚨 Сбои", callback_data="show_alarms")
    builder.button(text="🔧 Работы", callback_data="show_maintenances")
    builder.button(text="❌ Закрыть", callback_data="close_selection")
    builder.adjust(1)
    return builder.as_markup()


def create_refresh_keyboard(current_page: int = 0, total_pages: int = 1) -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопками обновления и навигации"""
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
