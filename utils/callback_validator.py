"""
Утилиты для валидации callback_data в обработчиках.
Упрощают проверку корректности callback запросов.
"""
import logging
from typing import Optional, List

from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)


async def validate_callback(
    callback: CallbackQuery,
    expected_prefix: str,
    valid_values: Optional[List[str]] = None
) -> bool:
    """
    Валидирует callback_data и отвечает на callback при ошибке.
    
    Args:
        callback: CallbackQuery объект
        expected_prefix: Ожидаемый префикс callback_data (например, "message_type_")
        valid_values: Список допустимых значений (опционально)
    
    Returns:
        True если валидация прошла, False если нет
    """
    user_id = callback.from_user.id
    
    # Проверка префикса
    if not callback.data.startswith(expected_prefix):
        logger.warning(f"[{user_id}] Некорректный callback_data: {callback.data}, ожидался префикс: {expected_prefix}")
        await callback.answer("❌ Некорректный запрос", show_alert=True)
        return False
    
    # Проверка допустимых значений (если указаны)
    if valid_values is not None and callback.data not in valid_values:
        logger.warning(f"[{user_id}] Неизвестное значение callback_data: {callback.data}, допустимые: {valid_values}")
        await callback.answer("❌ Неизвестное значение", show_alert=True)
        return False
    
    return True


async def extract_callback_value(
    callback: CallbackQuery,
    prefix: str,
    separator: str = "_"
) -> Optional[str]:
    """
    Извлекает значение из callback_data после префикса.
    
    Args:
        callback: CallbackQuery объект
        prefix: Префикс callback_data (например, "message_type_")
        separator: Разделитель для парсинга (по умолчанию "_")
    
    Returns:
        Извлеченное значение или None при ошибке
    
    Examples:
        callback.data = "message_type_alarm" -> возвращает "alarm"
        callback.data = "svc_Naumen" -> возвращает "Naumen"
    """
    if not await validate_callback(callback, prefix):
        return None
    
    try:
        # Убираем префикс и разделяем по separator
        value = callback.data[len(prefix):]
        # Если используется separator, берем последнюю часть
        if separator in value:
            parts = value.split(separator)
            # Возвращаем последнюю часть или объединяем все после префикса
            return separator.join(parts[1:]) if len(parts) > 1 else parts[0]
        return value
    except Exception as e:
        logger.error(f"[{callback.from_user.id}] Ошибка извлечения значения из callback_data: {e}")
        await callback.answer("❌ Ошибка обработки", show_alert=True)
        return None


async def validate_callback_in(
    callback: CallbackQuery,
    valid_values: List[str]
) -> bool:
    """
    Проверяет, что callback_data находится в списке допустимых значений.
    
    Args:
        callback: CallbackQuery объект
        valid_values: Список допустимых значений
    
    Returns:
        True если значение допустимо, False если нет
    """
    user_id = callback.from_user.id
    
    if callback.data not in valid_values:
        logger.warning(f"[{user_id}] Некорректный callback_data: {callback.data}, допустимые: {valid_values}")
        await callback.answer("❌ Некорректный запрос", show_alert=True)
        return False
    
    return True
