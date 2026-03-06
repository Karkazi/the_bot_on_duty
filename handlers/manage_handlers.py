"""
Основной роутер для обработчиков управления событиями.
Импортирует и объединяет все модули обработчиков.
"""
import logging
from aiogram import Router

# Импортируем роутеры из модулей
from .manage import router as manage_router
from .manage.scm import handle_scm_alarm_close
from .manage.reminders import check_reminders, auto_close_alarm_by_jira_status

logger = logging.getLogger(__name__)

# Создаем основной роутер и включаем все подроутеры
router = Router()
router.include_router(manage_router)

# Экспортируем функции для использования в других модулях
__all__ = ["router", "check_reminders", "auto_close_alarm_by_jira_status", "handle_scm_alarm_close"]
