"""
Middleware для централизованной обработки ошибок.
"""
import logging
import traceback
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramAPIError,
    TelegramNetworkError,
    TelegramServerError,
    TelegramRetryAfter
)

from utils.exceptions import (
    BotError,
    ValidationError,
    PermissionError,
    NotFoundError,
    JiraAPIError,
    ChannelError,
)

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseMiddleware):
    """
    Middleware для обработки ошибок в обработчиках.
    Логирует ошибки и отправляет понятные сообщения пользователям.
    """
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        
        except ValidationError as e:
            logger.warning(f"Ошибка валидации: {e}", exc_info=True)
            await self._send_error_message(event, f"⚠️ {str(e)}")
            return None
        
        except PermissionError as e:
            logger.warning(f"Ошибка прав доступа: {e}", exc_info=True)
            await self._send_error_message(event, f"❌ {str(e)}")
            return None
        
        except NotFoundError as e:
            logger.warning(f"Ресурс не найден: {e}", exc_info=True)
            await self._send_error_message(event, f"❌ {str(e)}")
            return None
        
        except JiraAPIError as e:
            logger.error(f"Ошибка Jira API: {e}", exc_info=True)
            await self._send_error_message(
                event,
                "❌ Ошибка при работе с Jira. Попробуйте позже или обратитесь к администратору."
            )
            return None
        
        except ChannelError as e:
            logger.error(f"Ошибка канала: {e}", exc_info=True)
            await self._send_error_message(
                event,
                "❌ Ошибка при отправке в канал. Проверьте логи."
            )
            return None
        
        except TelegramBadRequest as e:
            logger.error(f"Ошибка Telegram API (BadRequest): {e}", exc_info=True)
            # Не отправляем сообщение пользователю для Telegram ошибок
            return None
        
        except TelegramForbiddenError as e:
            logger.error(f"Ошибка Telegram API (Forbidden): {e}", exc_info=True)
            return None
        
        except TelegramNetworkError as e:
            # Сетевые ошибки - логируем, но не отправляем сообщение пользователю
            # (retry должен быть обработан на уровне отправки сообщения)
            logger.warning(f"Сетевая ошибка Telegram API: {e}")
            # Пытаемся отправить сообщение об ошибке, но не критично если не получится
            try:
                await self._send_error_message(
                    event,
                    "⚠️ Временная проблема с соединением. Попробуйте еще раз."
                )
            except Exception as send_err:
                logger.debug("Не удалось отправить сообщение об ошибке сети пользователю: %s", send_err)
            return None
            
        except TelegramServerError as e:
            # Ошибки сервера Telegram - временные проблемы
            logger.warning(f"Ошибка сервера Telegram: {e}")
            try:
                await self._send_error_message(
                    event,
                    "⚠️ Временная проблема на стороне Telegram. Попробуйте через несколько секунд."
                )
            except Exception as send_err:
                logger.debug("Не удалось отправить сообщение об ошибке сервера пользователю: %s", send_err)
            return None
            
        except TelegramRetryAfter as e:
            # Telegram просит подождать - логируем
            logger.warning(f"Telegram просит подождать {e.retry_after} секунд")
            return None
            
        except TelegramAPIError as e:
            logger.error(f"Ошибка Telegram API: {e}", exc_info=True)
            return None
        
        except BotError as e:
            logger.error(f"Ошибка бота: {e}", exc_info=True)
            await self._send_error_message(
                event,
                "❌ Произошла ошибка. Попробуйте позже или обратитесь к администратору."
            )
            return None
        
        except Exception as e:
            # Неожиданные ошибки - логируем полностью
            logger.critical(
                f"Неожиданная ошибка: {e}\n{traceback.format_exc()}",
                exc_info=True
            )
            await self._send_error_message(
                event,
                "❌ Произошла неожиданная ошибка. Администратор уведомлен."
            )
            return None
    
    async def _send_error_message(self, event: TelegramObject, message: str) -> None:
        """
        Отправляет понятное сообщение об ошибке пользователю.
        
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

