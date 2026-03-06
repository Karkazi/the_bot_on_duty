"""
Главные клавиатуры бота.
Содержит основные клавиатуры: главное меню, выбор типа сообщения, отмена и т.д.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


def create_main_keyboard(user_id: int = None) -> ReplyKeyboardMarkup:
    """
    Создает главную клавиатуру.
    
    Args:
        user_id: ID пользователя (не используется, оставлен для обратной совместимости)
    """
    from aiogram.types import KeyboardButton

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
    """Создает клавиатуру для выбора типа сообщения"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🚨 Сбой", callback_data="message_type_alarm"),
        InlineKeyboardButton(text="🔧 Работа", callback_data="message_type_maintenance")
    )
    builder.row(
        InlineKeyboardButton(text="📝 Обычное сообщение", callback_data="message_type_regular")
    )
    return builder.as_markup()


def create_cancel_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопкой отмены"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
    )
    return builder.as_markup()


def create_yes_no_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопками Да/Нет"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data="yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data="no")
    )
    return builder.as_markup()


def create_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для подтверждения отправки"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📩 Отправить", callback_data="confirm_send"),
        InlineKeyboardButton(text="🚫 Не отправлять", callback_data="confirm_cancel")
    )
    return builder.as_markup()
