"""
Клавиатуры для работы с авариями (alarms).
Содержит клавиатуры выбора уровня проблемы, сервиса, опций Jira и SCM.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import PROBLEM_LEVELS, PROBLEM_SERVICES


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


def create_skip_photo_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура «Пропустить» для шага прикрепления фото к обычному сообщению."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="regular_skip_photo")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
    )
    return builder.as_markup()


def create_petlocal_option_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора публикации на Петлокале."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Публикуем", callback_data="petlocal_publish"),
        InlineKeyboardButton(text="❌ Не публикуем", callback_data="petlocal_skip")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")
    )
    return builder.as_markup()
