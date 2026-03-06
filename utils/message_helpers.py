"""
Утилиты для работы с сообщениями Telegram.
Упрощают отправку и редактирование сообщений с автоматическим retry.
"""
import logging
from typing import Optional, Union

from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, ReplyKeyboardMarkup
from utils.telegram_retry import safe_send_message, safe_edit_message

logger = logging.getLogger(__name__)


class MessageHelper:
    """Утилиты для работы с сообщениями"""
    
    @staticmethod
    async def send_or_edit(
        target: Union[Message, CallbackQuery],
        text: str,
        reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup]] = None,
        parse_mode: str = 'HTML'
    ) -> bool:
        """
        Отправляет новое сообщение или редактирует существующее.
        
        Если target - CallbackQuery, пытается отредактировать сообщение.
        Если редактирование не удалось, отправляет новое сообщение.
        Если target - Message, отправляет новое сообщение.
        
        Args:
            target: Message или CallbackQuery объект
            text: Текст сообщения
            reply_markup: Клавиатура (опционально)
            parse_mode: Режим парсинга (по умолчанию 'HTML')
        
        Returns:
            True если операция успешна, False если нет
        """
        try:
            if isinstance(target, CallbackQuery):
                message = target.message
                if message:
                    # Пытаемся отредактировать существующее сообщение
                    result = await safe_edit_message(
                        message,
                        text,
                        reply_markup,
                        parse_mode
                    )
                    if result is None:
                        # Fallback на новое сообщение
                        logger.debug(f"[{target.from_user.id}] Редактирование не удалось, отправляем новое сообщение")
                        await safe_send_message(
                            message,
                            text,
                            reply_markup,
                            parse_mode
                        )
                else:
                    logger.warning(f"[{target.from_user.id}] CallbackQuery не содержит message")
                    return False
            else:
                # Отправляем новое сообщение
                await safe_send_message(
                    target,
                    text,
                    reply_markup,
                    parse_mode
                )
            return True
        except Exception as e:
            logger.error(f"Ошибка при отправке/редактировании сообщения: {e}", exc_info=True)
            return False
    
    @staticmethod
    async def send_with_fallback(
        message: Message,
        text: str,
        reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup]] = None,
        parse_mode: str = 'HTML',
        fallback_text: Optional[str] = None
    ) -> bool:
        """
        Отправляет сообщение с fallback текстом при ошибке.
        
        Args:
            message: Message объект
            text: Основной текст сообщения
            reply_markup: Клавиатура (опционально)
            parse_mode: Режим парсинга
            fallback_text: Текст для отправки при ошибке (опционально)
        
        Returns:
            True если операция успешна, False если нет
        """
        result = await safe_send_message(message, text, reply_markup, parse_mode)
        if result is None and fallback_text:
            logger.warning(f"[{message.from_user.id}] Не удалось отправить основное сообщение, используем fallback")
            await safe_send_message(message, fallback_text, parse_mode=parse_mode)
            return True
        return result is not None
    
    @staticmethod
    async def answer_callback_safe(
        callback: CallbackQuery,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> bool:
        """
        Безопасно отвечает на callback query.
        
        Args:
            callback: CallbackQuery объект
            text: Текст ответа (опционально)
            show_alert: Показать как alert
        
        Returns:
            True если операция успешна, False если нет
        """
        from utils.telegram_retry import safe_answer_callback
        return await safe_answer_callback(callback, text, show_alert)
