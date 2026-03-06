"""
Модуль обработчиков для создания аварий.
Экспортирует роутер для регистрации в основном диспетчере.
"""
from .creation import router as creation_router
from .calendar import router as calendar_router
from .confirmation import router as confirmation_router
from .regular_message import router as regular_router
from .maintenance import router as maintenance_router
from .cancel import router as cancel_router

# Объединяем все роутеры
from aiogram import Router

router = Router()
router.include_router(creation_router)
router.include_router(calendar_router)
router.include_router(confirmation_router)
router.include_router(regular_router)
router.include_router(maintenance_router)
router.include_router(cancel_router)

__all__ = ["router"]
