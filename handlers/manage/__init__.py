"""
Модуль обработчиков для управления событиями.
Экспортирует роутер для регистрации в основном диспетчере.
"""
from .stop import router as stop_router
from .extend import router as extend_router
from .reminders import router as reminders_router
from .scm import handle_scm_alarm_close

# Объединяем все роутеры
from aiogram import Router

router = Router()
router.include_router(stop_router)
router.include_router(extend_router)
router.include_router(reminders_router)

# Экспортируем функцию для использования в других модулях
__all__ = ["router", "handle_scm_alarm_close"]
