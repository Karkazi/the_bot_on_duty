"""
Декораторы для обработчиков бота.
Упрощают проверку прав доступа и обработку ошибок.
"""
import logging
from functools import wraps
from typing import Callable, Any, Awaitable, Union

from aiogram.types import Message, CallbackQuery
from utils.helpers import is_admin, is_superadmin

logger = logging.getLogger(__name__)


async def _send_permission_denied(event: Union[Message, CallbackQuery]) -> None:
    """
    Отправляет сообщение об отказе в доступе.
    
    Args:
        event: Событие Telegram (Message или CallbackQuery)
    """
    error_message = (
        "❌ У вас нет прав для выполнения этой команды.\n"
        "Обратитесь к администратору для получения доступа."
    )
    
    try:
        if isinstance(event, Message):
            await event.answer(error_message, parse_mode='HTML')
        elif isinstance(event, CallbackQuery):
            await event.answer("❌ Недостаточно прав", show_alert=True)
            if event.message:
                await event.message.answer(error_message, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения об отказе в доступе: {e}")


def require_admin(func: Callable) -> Callable:
    """
    Декоратор для проверки прав администратора.
    
    Если пользователь не является администратором, отправляется сообщение
    об отказе в доступе и функция не выполняется.
    
    Args:
        func: Функция-обработчик
    
    Returns:
        Обернутая функция с проверкой прав
    """
    @wraps(func)
    async def wrapper(event: Union[Message, CallbackQuery], *args: Any, **kwargs: Any) -> Any:
        # Получаем user_id в зависимости от типа события
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            logger.error(f"Неизвестный тип события: {type(event)}")
            return None
        
        if not is_admin(user_id):
            logger.warning(f"[{user_id}] Попытка доступа без прав администратора: {func.__name__}")
            await _send_permission_denied(event)
            return None
        
        return await func(event, *args, **kwargs)
    
    return wrapper


def require_superadmin(func: Callable) -> Callable:
    """
    Декоратор для проверки прав суперадминистратора.
    
    Если пользователь не является суперадминистратором, отправляется сообщение
    об отказе в доступе и функция не выполняется.
    
    Args:
        func: Функция-обработчик
    
    Returns:
        Обернутая функция с проверкой прав
    """
    @wraps(func)
    async def wrapper(event: Union[Message, CallbackQuery], *args: Any, **kwargs: Any) -> Any:
        # Получаем user_id в зависимости от типа события
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            logger.error(f"Неизвестный тип события: {type(event)}")
            return None
        
        if not is_superadmin(user_id):
            logger.warning(f"[{user_id}] Попытка доступа без прав суперадминистратора: {func.__name__}")
            await _send_permission_denied(event)
            return None
        
        return await func(event, *args, **kwargs)
    
    return wrapper
