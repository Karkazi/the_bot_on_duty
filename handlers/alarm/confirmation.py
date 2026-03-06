"""
Обработчики подтверждения и создания аварий/работ.
Делегируют создание в core.creation (общая логика для Telegram и MAX).
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from keyboards import create_main_keyboard
from utils.typing_indicators import show_typing_indicator
from core.creation import create_alarm, create_maintenance, send_regular_message

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "confirm_send")
async def confirm_send_callback(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик подтверждения отправки сообщения.
    Создает событие через core (авария, работа или обычное сообщение).
    """
    user_id = callback.from_user.id
    logger.info("[%s] Подтверждение отправки через callback", user_id)

    await show_typing_indicator(callback.bot, user_id, duration=0.5)

    data = await state.get_data()
    msg_type = data.get("type")

    async def reply_fn(text: str):
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=None)
        await callback.message.answer(
            "Выберите действие:",
            reply_markup=create_main_keyboard(user_id),
        )

    try:
        if msg_type == "alarm":
            await create_alarm(data, callback.bot, reply_fn, user_id)
        elif msg_type == "maintenance":
            await create_maintenance(data, callback.bot, reply_fn, user_id)
        elif msg_type == "regular":
            await send_regular_message(data, callback.bot, reply_fn, user_id)
        else:
            logger.warning("[%s] Неизвестный тип сообщения: %s", user_id, msg_type)
            await reply_fn("❌ Неизвестный тип сообщения")
        await state.clear()
    except Exception as e:
        logger.exception("[%s] Ошибка при завершении отправки: %s", user_id, e)
        await callback.message.edit_text(
            "❌ Не удалось отправить сообщение",
            reply_markup=None,
        )
        await state.clear()
