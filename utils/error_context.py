"""
Контекстные менеджеры для обработки ошибок Telegram API.
Упрощают обработку ошибок в обработчиках.
"""
import logging
from contextlib import asynccontextmanager
from typing import Union

from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramAPIError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramBadRequest,
    TelegramForbiddenError
)

logger = logging.getLogger(__name__)


async def _send_error_message(
    event: Union[Message, CallbackQuery],
    message: str
) -> None:
    """
    Отправляет сообщение об ошибке пользователю.
    
    Args:
        event: Событие Telegram (Message или CallbackQuery)
        message: Текст сообщения об ошибке
    """
    try:
        if isinstance(event, Message):
            await event.answer(
                f"{message}\n\n"
                "💡 Если проблема повторяется, обратитесь к администратору.",
                parse_mode='HTML'
            )
        elif isinstance(event, CallbackQuery):
            await event.answer(message, show_alert=True)
            if event.message:
                await event.message.answer(
                    f"{message}\n\n"
                    "💡 Если проблема повторяется, обратитесь к администратору.",
                    parse_mode='HTML'
                )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение об ошибке: {e}")


@asynccontextmanager
async def handle_telegram_errors(event: Union[Message, CallbackQuery]):
    """
    Контекстный менеджер для обработки ошибок Telegram API.
    
    Автоматически обрабатывает сетевые ошибки, ошибки сервера и другие
    ошибки Telegram API, отправляя понятные сообщения пользователю.
    
    Args:
        event: Событие Telegram (Message или CallbackQuery)
    
    Examples:
        async with handle_telegram_errors(message):
            await bot.send_message(...)
    """
    try:
        yield
    except TelegramRetryAfter as e:
        # Telegram просит подождать - это не критичная ошибка
        logger.warning(f"Telegram просит подождать {e.retry_after} секунд")
        # Не отправляем сообщение пользователю, так как это временная проблема
    except TelegramNetworkError as e:
        logger.warning(f"Сетевая ошибка Telegram: {e}")
        await _send_error_message(event, "⚠️ Временная проблема с соединением. Попробуйте еще раз.")
    except TelegramServerError as e:
        logger.warning(f"Ошибка сервера Telegram: {e}")
        await _send_error_message(event, "⚠️ Временная проблема на стороне Telegram. Попробуйте через несколько секунд.")
    except TelegramBadRequest as e:
        logger.error(f"Ошибка запроса Telegram (BadRequest): {e}")
        await _send_error_message(event, "❌ Ошибка в запросе. Проверьте правильность данных.")
    except TelegramForbiddenError as e:
        logger.error(f"Ошибка доступа Telegram (Forbidden): {e}")
        await _send_error_message(event, "❌ Нет доступа к выполнению операции. Проверьте права бота.")
    except TelegramAPIError as e:
        logger.error(f"Ошибка Telegram API: {e}")
        await _send_error_message(event, "❌ Ошибка при выполнении операции. Попробуйте позже.")
    except Exception as e:
        # Неожиданные ошибки
        logger.error(f"Неожиданная ошибка: {e}", exc_info=True)
        await _send_error_message(event, "❌ Произошла неожиданная ошибка. Администратор уведомлен.")


@asynccontextmanager
async def handle_network_errors(event: Union[Message, CallbackQuery]):
    """
    Контекстный менеджер для обработки только сетевых ошибок.
    
    Используется для операций, где сетевые ошибки ожидаемы и должны
    быть обработаны отдельно от других ошибок.
    
    Args:
        event: Событие Telegram (Message или CallbackQuery)
    """
    try:
        yield
    except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter) as e:
        logger.warning(f"Сетевая ошибка: {e}")
        raise  # Пробрасываем дальше для обработки retry логикой
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}", exc_info=True)
        raise
