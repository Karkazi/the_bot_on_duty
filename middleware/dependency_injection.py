"""
Middleware для внедрения зависимостей (Dependency Injection).
Позволяет передавать bot_state и другие зависимости через контекст.
"""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot_state import BotState

logger = logging.getLogger(__name__)


class DependencyInjectionMiddleware(BaseMiddleware):
    """
    Middleware для внедрения зависимостей в обработчики.
    
    Добавляет в data:
    - bot_state: экземпляр BotState
    - Можно расширить для других зависимостей
    """
    
    def __init__(self, bot_state: BotState):
        """
        Args:
            bot_state: Экземпляр BotState для внедрения
        """
        self.bot_state = bot_state
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Внедряем зависимости в контекст
        data['bot_state'] = self.bot_state
        
        return await handler(event, data)

