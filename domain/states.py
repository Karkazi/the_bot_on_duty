# domain/states.py
"""
Централизованное определение всех FSM состояний бота.
Импортируется во всех обработчиках для избежания дублирования.
"""
from aiogram.fsm.state import State, StatesGroup


class NewMessageStates(StatesGroup):
    """Состояния для создания нового сообщения"""
    SELECTING_TYPE = State()
    ENTER_TITLE = State()
    ENTER_DESCRIPTION = State()
    ENTER_LEVEL = State()
    ENTER_SERVICE = State()
    SELECT_JIRA_OPTION = State()  # Выбор создания задачи в Jira
    SELECT_SCM_OPTION = State()  # Выбор создания темы в SCM (только для сбоев без Jira)
    ENTER_FIX_TIME = State()
    ENTER_START_TIME = State()
    ENTER_END_TIME = State()
    ENTER_UNAVAILABLE_SERVICES = State()
    ENTER_MESSAGE_TEXT = State()
    ENTER_MESSAGE_PHOTO = State()     # Опционально: фото к обычному сообщению
    SELECT_PETLOCAL_OPTION = State()  # Выбор публикации на Петлокале
    CONFIRMATION = State()


class StopStates(StatesGroup):
    """Состояния для управления событиями (остановка/продление)"""
    SELECT_TYPE = State()           # Выбор типа события: сбой или работа
    SELECT_ACTION = State()         # Выбор действия: остановить / продлить
    SELECT_ALARM_DURATION = State() # Время продления сбоя
    ENTER_ALARM_DURATION_MANUAL = State() # Ввод длительности продления сбоя вручную
    ENTER_MAINTENANCE_END = State() # Новое время окончания работы
    SELECT_ITEM = State()           # Выбор конкретного события


class ReminderStates(StatesGroup):
    """Состояния для обработки напоминаний"""
    WAITING_FOR_EXTENSION = State()


class CalendarStates(StatesGroup):
    """Состояния для выбора даты через календарь"""
    SELECT_MONTH = State()      # Выбор месяца
    SELECT_DAY = State()         # Выбор дня
    SELECT_HOUR = State()        # Выбор часа
    SELECT_MINUTE = State()      # Выбор минуты

