"""
Настройка логирования (альтернативный модуль; основной вход — main.setup_logging).
"""
import logging

from utils.app_paths import BOT_LOG_FILE

def setup_logging():
    """Настраивает логирование для приложения"""
    # Формат логов
    log_format = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"

    # Единый файл логов в каталоге проекта (как в main.py)
    log_file = str(BOT_LOG_FILE)
    
    # Логирование в файл
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(log_format))
    
    # Логирование в консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # Основная настройка логгера
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[file_handler, console_handler]
    ) 