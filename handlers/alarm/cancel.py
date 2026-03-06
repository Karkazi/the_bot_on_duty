"""
Обработчики отмены действий.
Содержит логику отмены различных операций.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from keyboards import create_main_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "cancel")
async def cancel_action_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены действия"""
    user_id = callback.from_user.id
    logger.info(f"[{user_id}] Отмена действия через callback")
    await state.clear()
    await callback.message.edit_text("🚫 Действие отменено", reply_markup=None)
    await callback.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
    await callback.answer()


@router.callback_query(F.data == "cancel_action")
async def cancel_action_callback_alt(callback: CallbackQuery, state: FSMContext):
    """Альтернативный обработчик отмены (используется в календаре)"""
    user_id = callback.from_user.id
    logger.info(f"[{user_id}] Отмена действия через cancel_action")
    await state.clear()
    await callback.message.edit_text("🚫 Действие отменено", reply_markup=None)
    await callback.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
    await callback.answer()


@router.callback_query(F.data == "confirm_cancel")
async def cancel_send_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик отмены отправки"""
    user_id = callback.from_user.id
    logger.info(f"[{user_id}] Отмена отправки через callback")
    await state.clear()
    await callback.message.edit_text("🚫 Действие отменено", reply_markup=None)
    await callback.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
    await callback.answer()
