"""
Утилиты для отображения индикаторов печати (typing indicators).
Показывают пользователю, что бот обрабатывает запрос.
"""
import asyncio
from typing import Optional
from aiogram import Bot
from aiogram.enums import ChatAction

logger = None  # Будет инициализирован при первом использовании


async def show_typing_indicator(
    bot: Bot,
    chat_id: int,
    duration: float = 1.0
) -> None:
    """
    Показывает индикатор печати в чате.
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        duration: Длительность показа индикатора (секунды)
    """
    try:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        if duration > 0:
            await asyncio.sleep(min(duration, 5.0))  # Максимум 5 секунд
    except Exception as e:
        # Логируем только если логгер доступен
        if logger:
            logger.debug(f"Не удалось показать индикатор печати: {e}")


async def show_typing_while_processing(
    bot: Bot,
    chat_id: int,
    coro,
    *args,
    **kwargs
):
    """
    Показывает индикатор печати во время выполнения корутины.
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        coro: Корутина для выполнения
        *args, **kwargs: Аргументы для корутины
    
    Returns:
        Результат выполнения корутины
    """
    # Запускаем индикатор и корутину параллельно
    typing_task = asyncio.create_task(
        _continuous_typing(bot, chat_id)
    )
    
    try:
        result = await coro(*args, **kwargs)
        return result
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


async def _continuous_typing(bot: Bot, chat_id: int):
    """Непрерывно показывает индикатор печати"""
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(3)  # Telegram требует обновлять каждые 3-5 секунд
    except asyncio.CancelledError:
        pass
    except Exception:
        pass  # Игнорируем ошибки при отмене

