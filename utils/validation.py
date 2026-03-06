# utils/validation.py
"""
Утилиты для валидации пользовательского ввода
"""
import re
import html
from typing import Optional, Tuple
from domain.constants import MAX_TITLE_LENGTH, MAX_DESCRIPTION_LENGTH, MAX_MESSAGE_TEXT_LENGTH


def sanitize_html(text: str) -> str:
    """
    Санитизация HTML-тегов в пользовательском вводе.
    Экранирует все HTML-символы для безопасности.
    """
    return html.escape(text, quote=True)


def validate_text_length(text: str, max_length: int, field_name: str = "текст") -> Tuple[bool, Optional[str]]:
    """
    Валидация длины текста.
    
    Returns:
        (is_valid, error_message)
    """
    if len(text) > max_length:
        return False, f"⚠️ {field_name.capitalize()} слишком длинный. Максимум {max_length} символов."
    return True, None


def validate_title(title: str) -> Tuple[bool, Optional[str]]:
    """
    Валидация заголовка.
    
    Args:
        title: Заголовок для валидации
    
    Returns:
        Кортеж (is_valid, error_message)
        - is_valid: True если валидно, False если есть ошибки
        - error_message: Сообщение об ошибке или None
    """
    if not title or not title.strip():
        return False, "⚠️ Заголовок не может быть пустым"
    return validate_text_length(title, MAX_TITLE_LENGTH, "заголовок")


def validate_description(description: str) -> Tuple[bool, Optional[str]]:
    """
    Валидация описания проблемы или работ.
    
    Args:
        description: Описание для валидации
    
    Returns:
        Кортеж (is_valid, error_message)
        - is_valid: True если валидно, False если есть ошибки
        - error_message: Сообщение об ошибке или None
    """
    if not description or not description.strip():
        return False, "⚠️ Описание не может быть пустым"
    return validate_text_length(description, MAX_DESCRIPTION_LENGTH, "описание")


def validate_message_text(text: str) -> Tuple[bool, Optional[str]]:
    """
    Валидация текста обычного сообщения.
    
    Args:
        text: Текст сообщения для валидации
    
    Returns:
        Кортеж (is_valid, error_message)
        - is_valid: True если валидно, False если есть ошибки
        - error_message: Сообщение об ошибке или None
    """
    if not text or not text.strip():
        return False, "⚠️ Текст сообщения не может быть пустым"
    return validate_text_length(text, MAX_MESSAGE_TEXT_LENGTH, "текст сообщения")


def validate_datetime_format(datetime_str: str, format_str: str = "%d.%m.%Y %H:%M") -> Tuple[bool, Optional[str]]:
    """
    Валидация формата даты и времени.
    
    Returns:
        (is_valid, error_message)
    """
    try:
        from datetime import datetime
        datetime.strptime(datetime_str.strip(), format_str)
        return True, None
    except ValueError:
        return False, f"⚠️ Неверный формат даты и времени. Используйте формат: {format_str.replace('%', '')}"

