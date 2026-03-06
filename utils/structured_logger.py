"""
Настройка структурированного логирования.
Использует стандартный logging с JSON форматированием для лучшей читаемости.
"""
import logging
import json
from datetime import datetime
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """
    Форматтер для структурированного логирования в JSON.
    Упрощенная версия без structlog для совместимости.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Форматирует запись лога в JSON"""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Добавляем дополнительные поля, если есть
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        
        if hasattr(record, "alarm_id"):
            log_data["alarm_id"] = record.alarm_id
        
        if hasattr(record, "work_id"):
            log_data["work_id"] = record.work_id
        
        # Добавляем информацию об исключении, если есть
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Добавляем путь и строку, если нужно
        if self.include_location():
            log_data["pathname"] = record.pathname
            log_data["lineno"] = record.lineno
            log_data["funcName"] = record.funcName
        
        return json.dumps(log_data, ensure_ascii=False)
    
    def include_location(self) -> bool:
        """Определяет, включать ли информацию о местоположении"""
        return False  # По умолчанию не включаем для читаемости


class StructuredLogger:
    """
    Обертка для структурированного логирования.
    Позволяет добавлять контекстные поля к логам.
    """
    
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """
        Получает логгер с контекстными методами.
        
        Args:
            name: Имя логгера
        
        Returns:
            Логгер с дополнительными методами
        """
        logger = logging.getLogger(name)
        
        # Добавляем методы для логирования с контекстом
        original_info = logger.info
        original_warning = logger.warning
        original_error = logger.error
        original_debug = logger.debug
        
        def info_with_context(msg: str, *args, **kwargs):
            """Логирование с контекстом"""
            extra = kwargs.get("extra", {})
            if "user_id" in kwargs:
                extra["user_id"] = kwargs.pop("user_id")
            if "alarm_id" in kwargs:
                extra["alarm_id"] = kwargs.pop("alarm_id")
            if "work_id" in kwargs:
                extra["work_id"] = kwargs.pop("work_id")
            kwargs["extra"] = extra
            return original_info(msg, *args, **kwargs)
        
        def warning_with_context(msg: str, *args, **kwargs):
            """Логирование с контекстом"""
            extra = kwargs.get("extra", {})
            if "user_id" in kwargs:
                extra["user_id"] = kwargs.pop("user_id")
            if "alarm_id" in kwargs:
                extra["alarm_id"] = kwargs.pop("alarm_id")
            if "work_id" in kwargs:
                extra["work_id"] = kwargs.pop("work_id")
            kwargs["extra"] = extra
            return original_warning(msg, *args, **kwargs)
        
        def error_with_context(msg: str, *args, **kwargs):
            """Логирование с контекстом"""
            extra = kwargs.get("extra", {})
            if "user_id" in kwargs:
                extra["user_id"] = kwargs.pop("user_id")
            if "alarm_id" in kwargs:
                extra["alarm_id"] = kwargs.pop("alarm_id")
            if "work_id" in kwargs:
                extra["work_id"] = kwargs.pop("work_id")
            kwargs["extra"] = extra
            return original_error(msg, *args, **kwargs)
        
        def debug_with_context(msg: str, *args, **kwargs):
            """Логирование с контекстом"""
            extra = kwargs.get("extra", {})
            if "user_id" in kwargs:
                extra["user_id"] = kwargs.pop("user_id")
            if "alarm_id" in kwargs:
                extra["alarm_id"] = kwargs.pop("alarm_id")
            if "work_id" in kwargs:
                extra["work_id"] = kwargs.pop("work_id")
            kwargs["extra"] = extra
            return original_debug(msg, *args, **kwargs)
        
        logger.info = info_with_context
        logger.warning = warning_with_context
        logger.error = error_with_context
        logger.debug = debug_with_context
        
        return logger


def setup_structured_logging(use_json: bool = False, level: int = logging.INFO):
    """
    Настраивает структурированное логирование.
    
    Args:
        use_json: Использовать JSON формат (по умолчанию False для читаемости)
        level: Уровень логирования
    """
    log_format = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    
    if use_json:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(log_format)
    
    # Логирование в файл
    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    
    # Логирование в консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    
    # Основная настройка логгера
    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=[file_handler, console_handler]
    )

