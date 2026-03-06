"""
Базовые классы для обработчиков состояний.
Упрощают создание новых обработчиков и обеспечивают единообразный подход.
"""
from abc import ABC, abstractmethod
from typing import Union, Any

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message, CallbackQuery

from utils.fsm_helpers import FSMHelper
from utils.message_helpers import MessageHelper


class BaseStateHandler(ABC):
    """
    Базовый класс для обработчиков состояний FSM.
    
    Предоставляет общие методы для валидации, работы с state и отправки сообщений.
    """
    
    def __init__(self):
        """Инициализация базового обработчика"""
        self.fsm_helper = FSMHelper()
        self.message_helper = MessageHelper()
    
    @abstractmethod
    async def handle(
        self,
        event: Union[Message, CallbackQuery],
        state: FSMContext,
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """
        Обработка события.
        
        Args:
            event: Событие Telegram (Message или CallbackQuery)
            state: FSM контекст
            *args: Дополнительные позиционные аргументы
            **kwargs: Дополнительные именованные аргументы
        
        Returns:
            Результат обработки (опционально)
        """
        pass
    
    async def validate_and_proceed(
        self,
        event: Union[Message, CallbackQuery],
        state: FSMContext,
        next_state: State,
        validation_func: callable = None,
        *validation_args: Any,
        **validation_kwargs: Any
    ) -> bool:
        """
        Валидация данных и переход к следующему состоянию.
        
        Args:
            event: Событие Telegram
            state: FSM контекст
            next_state: Следующее состояние
            validation_func: Функция валидации (опционально)
            *validation_args: Аргументы для функции валидации
            **validation_kwargs: Именованные аргументы для функции валидации
        
        Returns:
            True если валидация прошла и переход выполнен, False если нет
        """
        # Выполняем валидацию, если указана функция
        if validation_func:
            try:
                is_valid = await validation_func(event, state, *validation_args, **validation_kwargs)
                if not is_valid:
                    return False
            except Exception as e:
                # Логируем ошибку валидации, но не прерываем выполнение
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Ошибка при валидации: {e}", exc_info=True)
                return False
        
        # Переходим к следующему состоянию
        try:
            await self.fsm_helper.set_state(state, next_state)
            return True
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка при переходе к состоянию: {e}", exc_info=True)
            return False
    
    async def get_user_id(self, event: Union[Message, CallbackQuery]) -> int:
        """
        Получает ID пользователя из события.
        
        Args:
            event: Событие Telegram
        
        Returns:
            ID пользователя
        """
        if isinstance(event, Message):
            return event.from_user.id
        elif isinstance(event, CallbackQuery):
            return event.from_user.id
        else:
            raise ValueError(f"Неизвестный тип события: {type(event)}")
    
    async def send_response(
        self,
        event: Union[Message, CallbackQuery],
        text: str,
        reply_markup: Any = None,
        parse_mode: str = 'HTML'
    ) -> bool:
        """
        Отправляет ответ пользователю.
        
        Args:
            event: Событие Telegram
            text: Текст ответа
            reply_markup: Клавиатура (опционально)
            parse_mode: Режим парсинга
        
        Returns:
            True если отправка успешна, False если нет
        """
        return await self.message_helper.send_or_edit(
            event,
            text,
            reply_markup,
            parse_mode
        )


class BaseCallbackHandler(BaseStateHandler):
    """
    Базовый класс для обработчиков callback query.
    
    Предоставляет дополнительные методы для работы с callback.
    """
    
    async def answer_callback(
        self,
        callback: CallbackQuery,
        text: str = None,
        show_alert: bool = False
    ) -> bool:
        """
        Отвечает на callback query.
        
        Args:
            callback: CallbackQuery объект
            text: Текст ответа (опционально)
            show_alert: Показать как alert
        
        Returns:
            True если ответ успешен, False если нет
        """
        return await self.message_helper.answer_callback_safe(
            callback,
            text,
            show_alert
        )


class BaseMessageHandler(BaseStateHandler):
    """
    Базовый класс для обработчиков сообщений.
    
    Предоставляет дополнительные методы для работы с сообщениями.
    """
    
    async def get_message_text(self, message: Message) -> str:
        """
        Получает текст сообщения.
        
        Args:
            message: Message объект
        
        Returns:
            Текст сообщения или пустая строка
        """
        return message.text or message.caption or ""
