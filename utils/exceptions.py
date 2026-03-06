"""
Кастомные исключения для бота.
Используются для централизованной обработки ошибок.
"""


class BotError(Exception):
    """Базовое исключение для всех ошибок бота"""
    pass


class ValidationError(BotError):
    """Ошибка валидации входных данных"""
    def __init__(self, message: str, field: str = None):
        super().__init__(message)
        self.field = field


class ConfigurationError(BotError):
    """Ошибка конфигурации"""
    pass


class StateError(BotError):
    """Ошибка работы с состоянием бота"""
    pass


class JiraAPIError(BotError):
    """Ошибка при работе с Jira API"""
    def __init__(self, message: str, status_code: int = None, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class TelegramAPIError(BotError):
    """Ошибка при работе с Telegram API"""
    pass


class ChannelError(BotError):
    """Ошибка при работе с каналом"""
    pass


class PermissionError(BotError):
    """Ошибка прав доступа"""
    pass


class NotFoundError(BotError):
    """Ресурс не найден"""
    pass

