"""
Основной роутер для обработчиков создания сообщений (аварий, работ, обычных сообщений).
Импортирует и объединяет все модули обработчиков.
"""
import logging
from aiogram import Router

# Импортируем роутеры из модулей
from .alarm import router as alarm_router

logger = logging.getLogger(__name__)

# Создаем основной роутер и включаем все подроутеры
router = Router()
router.include_router(alarm_router)

__all__ = ["router"]
