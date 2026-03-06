"""
Middleware для rate limiting запросов.
Защищает от злоупотреблений и спама.
"""
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from utils.exceptions import BotError

logger = logging.getLogger(__name__)


class RateLimiterMiddleware(BaseMiddleware):
    """
    Middleware для ограничения частоты запросов от одного пользователя.
    
    Настройки:
    - max_requests: максимальное количество запросов
    - time_window: временное окно в секундах
    """
    
    def __init__(self, max_requests: int = 10, time_window: int = 60):
        """
        Args:
            max_requests: Максимальное количество запросов за time_window
            time_window: Временное окно в секундах
        """
        self.max_requests = max_requests
        self.time_window = time_window
        # Хранилище: {user_id: [(timestamp, ...), ...]}
        self._requests: Dict[int, list] = defaultdict(list)
        # Время последнего предупреждения для пользователя
        self._last_warning: Dict[int, float] = {}
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем user_id из события
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
        
        if not user_id:
            # Если не можем определить пользователя, пропускаем
            return await handler(event, data)
        
        # Очищаем старые запросы
        current_time = time.time()
        self._cleanup_old_requests(user_id, current_time)
        
        # Проверяем лимит
        if len(self._requests[user_id]) >= self.max_requests:
            # Превышен лимит
            last_warning_time = self._last_warning.get(user_id, 0)
            
            # Предупреждаем не чаще раза в минуту
            if current_time - last_warning_time > 60:
                await self._send_rate_limit_warning(event, user_id)
                self._last_warning[user_id] = current_time
            
            logger.warning(
                f"Rate limit превышен для пользователя {user_id}: "
                f"{len(self._requests[user_id])} запросов за {self.time_window} секунд"
            )
            return None  # Блокируем запрос
        
        # Добавляем текущий запрос
        self._requests[user_id].append(current_time)
        
        # Выполняем обработчик
        return await handler(event, data)
    
    def _cleanup_old_requests(self, user_id: int, current_time: float) -> None:
        """Удаляет запросы старше time_window"""
        cutoff_time = current_time - self.time_window
        self._requests[user_id] = [
            timestamp for timestamp in self._requests[user_id]
            if timestamp > cutoff_time
        ]
    
    async def _send_rate_limit_warning(
        self,
        event: TelegramObject,
        user_id: int
    ) -> None:
        """Отправляет предупреждение о превышении лимита"""
        message = (
            f"⚠️ Слишком много запросов. "
            f"Подождите {self.time_window} секунд перед следующим запросом."
        )
        
        try:
            if isinstance(event, Message):
                await event.answer(message)
            elif isinstance(event, CallbackQuery):
                await event.answer(message, show_alert=True)
        except Exception as e:
            logger.error(f"Не удалось отправить предупреждение о rate limit: {e}")

