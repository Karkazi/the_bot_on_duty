"""
Утилиты для безопасной отправки сообщений через Telegram API с retry логикой.
Обрабатывает сетевые ошибки и временные сбои соединения.
"""
import asyncio
import logging
from typing import Optional, Any, Union

from aiogram import Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramAPIError,
    TelegramRetryAfter,
    TelegramServerError
)
from domain.constants import HTTP_MAX_RETRIES, HTTP_RETRY_DELAY

logger = logging.getLogger(__name__)

# Дополнительные настройки для Telegram API
TELEGRAM_MAX_RETRIES = 3
TELEGRAM_RETRY_DELAY = 1.0  # секунды
TELEGRAM_RETRY_DELAY_MULTIPLIER = 2.0  # Увеличиваем задержку с каждой попыткой


async def safe_send_message(
    bot_or_message: Union[Bot, Message],
    text: str,
    reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup]] = None,
    parse_mode: Optional[str] = None,
    **kwargs
) -> Optional[Message]:
    """
    Безопасная отправка сообщения с retry логикой для сетевых ошибок.
    
    Args:
        bot_or_message: Bot объект или Message для ответа
        text: Текст сообщения
        reply_markup: Клавиатура (опционально)
        parse_mode: Режим парсинга (HTML, Markdown и т.д.)
        **kwargs: Дополнительные параметры для метода answer/send_message
    
    Returns:
        Message объект при успехе, None при ошибке
    """
    if isinstance(bot_or_message, Message):
        bot = bot_or_message.bot
        send_method = bot_or_message.answer
    else:
        bot = bot_or_message
        send_method = bot.send_message
    
    last_exception = None
    
    for attempt in range(TELEGRAM_MAX_RETRIES):
        try:
            if isinstance(bot_or_message, Message):
                result = await send_method(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    **kwargs
                )
            else:
                # Для Bot нужен chat_id
                if "chat_id" not in kwargs:
                    logger.error("Для Bot объекта требуется указать chat_id")
                    return None
                result = await send_method(
                    chat_id=kwargs.pop("chat_id"),
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    **kwargs
                )
            
            if attempt > 0:
                logger.info(f"✅ Сообщение успешно отправлено после {attempt + 1} попытки")
            
            return result
            
        except TelegramRetryAfter as e:
            # Telegram просит подождать определенное время
            wait_time = e.retry_after
            logger.warning(f"⏳ Telegram просит подождать {wait_time} секунд (попытка {attempt + 1}/{TELEGRAM_MAX_RETRIES})")
            await asyncio.sleep(wait_time)
            last_exception = e
            continue
            
        except (TelegramNetworkError, TelegramServerError) as e:
            # Сетевые ошибки и ошибки сервера - повторяем
            delay = TELEGRAM_RETRY_DELAY * (TELEGRAM_RETRY_DELAY_MULTIPLIER ** attempt)
            logger.warning(
                f"⚠️ Сетевая ошибка при отправке сообщения (попытка {attempt + 1}/{TELEGRAM_MAX_RETRIES}): {e}\n"
                f"Повторная попытка через {delay:.1f} секунд..."
            )
            last_exception = e
            
            if attempt < TELEGRAM_MAX_RETRIES - 1:
                await asyncio.sleep(delay)
            else:
                logger.error(f"❌ Не удалось отправить сообщение после {TELEGRAM_MAX_RETRIES} попыток: {e}")
                break
                
        except TelegramAPIError as e:
            # Другие ошибки API (например, BadRequest) - не повторяем
            logger.error(f"❌ Ошибка Telegram API (не повторяем): {e}")
            return None
            
        except Exception as e:
            # Неожиданные ошибки
            logger.error(f"❌ Неожиданная ошибка при отправке сообщения: {e}", exc_info=True)
            return None
    
    # Если все попытки исчерпаны
    if last_exception:
        logger.error(
            f"❌ Не удалось отправить сообщение после {TELEGRAM_MAX_RETRIES} попыток.\n"
            f"Последняя ошибка: {last_exception}"
        )
    
    return None


async def safe_edit_message(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = None,
    **kwargs
) -> Optional[Message]:
    """
    Безопасное редактирование сообщения с retry логикой.
    
    Args:
        message: Сообщение для редактирования
        text: Новый текст
        reply_markup: Новая клавиатура (опционально)
        parse_mode: Режим парсинга
        **kwargs: Дополнительные параметры
    
    Returns:
        Message объект при успехе, None при ошибке
    """
    last_exception = None
    
    for attempt in range(TELEGRAM_MAX_RETRIES):
        try:
            result = await message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                **kwargs
            )
            
            if attempt > 0:
                logger.info(f"✅ Сообщение успешно отредактировано после {attempt + 1} попытки")
            
            return result
            
        except TelegramRetryAfter as e:
            wait_time = e.retry_after
            logger.warning(f"⏳ Telegram просит подождать {wait_time} секунд (попытка {attempt + 1}/{TELEGRAM_MAX_RETRIES})")
            await asyncio.sleep(wait_time)
            last_exception = e
            continue
            
        except (TelegramNetworkError, TelegramServerError) as e:
            delay = TELEGRAM_RETRY_DELAY * (TELEGRAM_RETRY_DELAY_MULTIPLIER ** attempt)
            logger.warning(
                f"⚠️ Сетевая ошибка при редактировании сообщения (попытка {attempt + 1}/{TELEGRAM_MAX_RETRIES}): {e}\n"
                f"Повторная попытка через {delay:.1f} секунд..."
            )
            last_exception = e
            
            if attempt < TELEGRAM_MAX_RETRIES - 1:
                await asyncio.sleep(delay)
            else:
                logger.error(f"❌ Не удалось отредактировать сообщение после {TELEGRAM_MAX_RETRIES} попыток: {e}")
                break
                
        except TelegramAPIError as e:
            # Другие ошибки API - не повторяем
            logger.error(f"❌ Ошибка Telegram API при редактировании (не повторяем): {e}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при редактировании сообщения: {e}", exc_info=True)
            return None
    
    if last_exception:
        logger.error(
            f"❌ Не удалось отредактировать сообщение после {TELEGRAM_MAX_RETRIES} попыток.\n"
            f"Последняя ошибка: {last_exception}"
        )
    
    return None


async def safe_answer_callback(
    callback: CallbackQuery,
    text: Optional[str] = None,
    show_alert: bool = False,
    **kwargs
) -> bool:
    """
    Безопасный ответ на callback query с retry логикой.
    
    Args:
        callback: CallbackQuery объект
        text: Текст ответа (опционально)
        show_alert: Показать как alert
        **kwargs: Дополнительные параметры
    
    Returns:
        True при успехе, False при ошибке
    """
    for attempt in range(TELEGRAM_MAX_RETRIES):
        try:
            await callback.answer(text=text, show_alert=show_alert, **kwargs)
            return True
            
        except TelegramRetryAfter as e:
            wait_time = e.retry_after
            logger.warning(f"⏳ Telegram просит подождать {wait_time} секунд (попытка {attempt + 1}/{TELEGRAM_MAX_RETRIES})")
            await asyncio.sleep(wait_time)
            continue
            
        except (TelegramNetworkError, TelegramServerError) as e:
            delay = TELEGRAM_RETRY_DELAY * (TELEGRAM_RETRY_DELAY_MULTIPLIER ** attempt)
            logger.warning(
                f"⚠️ Сетевая ошибка при ответе на callback (попытка {attempt + 1}/{TELEGRAM_MAX_RETRIES}): {e}\n"
                f"Повторная попытка через {delay:.1f} секунд..."
            )
            
            if attempt < TELEGRAM_MAX_RETRIES - 1:
                await asyncio.sleep(delay)
            else:
                logger.error(f"❌ Не удалось ответить на callback после {TELEGRAM_MAX_RETRIES} попыток: {e}")
                return False
                
        except TelegramAPIError as e:
            # Другие ошибки API - не критично для callback
            logger.warning(f"⚠️ Ошибка Telegram API при ответе на callback: {e}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при ответе на callback: {e}", exc_info=True)
            return False
    
    return False

