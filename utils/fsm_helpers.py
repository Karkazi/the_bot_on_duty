"""
Утилиты для работы с FSM (Finite State Machine).
Упрощают работу с состояниями и данными FSM.
"""
import logging
from typing import Any, Dict, Optional

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State

logger = logging.getLogger(__name__)


class FSMHelper:
    """Утилиты для работы с FSM"""
    
    @staticmethod
    async def get_data_safe(
        state: FSMContext,
        key: str,
        default: Any = None
    ) -> Any:
        """
        Безопасное получение данных из state.
        
        Args:
            state: FSM контекст
            key: Ключ для получения данных
            default: Значение по умолчанию, если ключ не найден
        
        Returns:
            Значение из state или default
        """
        try:
            data = await state.get_data()
            return data.get(key, default)
        except Exception as e:
            logger.error(f"Ошибка при получении данных из state: {e}", exc_info=True)
            return default
    
    @staticmethod
    async def get_all_data(state: FSMContext) -> Dict[str, Any]:
        """
        Безопасное получение всех данных из state.
        
        Args:
            state: FSM контекст
        
        Returns:
            Словарь с данными state или пустой словарь при ошибке
        """
        try:
            return await state.get_data()
        except Exception as e:
            logger.error(f"Ошибка при получении всех данных из state: {e}", exc_info=True)
            return {}
    
    @staticmethod
    async def update_and_log(
        state: FSMContext,
        user_id: int,
        **kwargs: Any
    ) -> None:
        """
        Обновляет state и логирует изменения.
        
        Args:
            state: FSM контекст
            user_id: ID пользователя для логирования
            **kwargs: Данные для обновления state
        """
        try:
            await state.update_data(**kwargs)
            logger.debug(f"[{user_id}] State обновлен: {list(kwargs.keys())}")
        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при обновлении state: {e}", exc_info=True)
    
    @staticmethod
    async def clear_state(
        state: FSMContext,
        user_id: Optional[int] = None
    ) -> None:
        """
        Очищает state и логирует.
        
        Args:
            state: FSM контекст
            user_id: ID пользователя для логирования (опционально)
        """
        try:
            await state.clear()
            if user_id:
                logger.debug(f"[{user_id}] State очищен")
        except Exception as e:
            logger.error(f"Ошибка при очистке state: {e}", exc_info=True)
    
    @staticmethod
    async def set_state(
        state: FSMContext,
        new_state: State,
        user_id: Optional[int] = None
    ) -> None:
        """
        Устанавливает новое состояние и логирует.
        
        Args:
            state: FSM контекст
            new_state: Новое состояние
            user_id: ID пользователя для логирования (опционально)
        """
        try:
            await state.set_state(new_state)
            if user_id:
                logger.debug(f"[{user_id}] Установлено состояние: {new_state}")
        except Exception as e:
            logger.error(f"Ошибка при установке состояния: {e}", exc_info=True)
    
    @staticmethod
    async def get_state_name(state: FSMContext) -> Optional[str]:
        """
        Получает имя текущего состояния.
        
        Args:
            state: FSM контекст
        
        Returns:
            Имя состояния или None
        """
        try:
            current_state = await state.get_state()
            return str(current_state) if current_state else None
        except Exception as e:
            logger.error(f"Ошибка при получении состояния: {e}", exc_info=True)
            return None
