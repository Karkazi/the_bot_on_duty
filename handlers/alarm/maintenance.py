"""
Обработчики для создания регламентных работ.
Содержит логику ввода времени работ вручную и недоступных сервисов.
"""
import logging
from datetime import datetime as dt
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from keyboards import create_cancel_keyboard, create_main_keyboard, create_confirmation_keyboard
from keyboards.alarm import create_petlocal_option_keyboard
from aiogram.types import CallbackQuery
from utils.callback_validator import validate_callback_in
from utils.telegram_retry import safe_edit_message
from utils.validation import validate_datetime_format, sanitize_html
from domain.states import NewMessageStates
from domain.constants import DATETIME_FORMAT

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "maint_method_manual")
async def handle_manual_method(call, state: FSMContext):
    """Обработчик выбора ручного ввода времени работ"""
    user_id = call.from_user.id
    logger.info(f"[{user_id}] Выбран способ ввода времени: ручной ввод")
    
    await call.message.edit_text(
        "⌛ Введите время начала работ в формате:\n"
        "• Например: «27.05.2025 14:00»",
        reply_markup=create_cancel_keyboard()
    )
    await state.set_state(NewMessageStates.ENTER_START_TIME)
    await call.answer()


@router.message(NewMessageStates.ENTER_START_TIME)
async def enter_start_time(message: Message, state: FSMContext):
    """Обработчик ввода времени начала работ"""
    time_str = message.text.strip()
    user_id = message.from_user.id
    logger.info(f"[{user_id}] Введено время начала: {time_str}")
    if time_str == "❌ Отмена":
        logger.info(f"[{user_id}] Отмена на этапе ENTER_START_TIME")
        await state.clear()
        await message.answer("🚫 Действие отменено", reply_markup=create_main_keyboard())
        return
    
    # Валидация формата даты
    is_valid, error_msg = validate_datetime_format(time_str, DATETIME_FORMAT)
    if not is_valid:
        logger.warning(f"[{user_id}] Неверный формат даты: {time_str}")
        await message.answer(error_msg, reply_markup=create_cancel_keyboard())
        return
    
    try:
        start_time = dt.strptime(time_str, DATETIME_FORMAT)
        await state.update_data(start_time=start_time.isoformat())
        logger.debug(f"[{user_id}] Время начала установлено: {start_time.isoformat()}")
        await message.answer(
            "⌛ Введите время окончания работ в формате:\n"
            "• Например: «27.05.2025 16:00»",
            reply_markup=create_cancel_keyboard()
        )
        await state.set_state(NewMessageStates.ENTER_END_TIME)
    except ValueError as e:
        logger.warning(f"[{user_id}] Ошибка парсинга даты: {e}")
        await message.answer(
            "⚠️ Неверный формат времени.\n"
            "Введите дату и время в формате:\n"
            "• Пример: «27.05.2025 14:00»",
            reply_markup=create_cancel_keyboard()
        )


@router.message(NewMessageStates.ENTER_END_TIME)
async def enter_end_time(message: Message, state: FSMContext):
    """Обработчик ввода времени окончания работ"""
    time_str = message.text.strip()
    user_id = message.from_user.id
    logger.info(f"[{user_id}] Введено время окончания: {time_str}")
    if time_str == "❌ Отмена":
        logger.info(f"[{user_id}] Отмена на этапе ENTER_END_TIME")
        await state.clear()
        await message.answer("🚫 Действие отменено", reply_markup=create_main_keyboard())
        return
    try:
        data = await state.get_data()
        start_time = dt.fromisoformat(data["start_time"])
        end_time = dt.strptime(time_str, DATETIME_FORMAT)
        if end_time < start_time:
            raise ValueError("Время окончания не может быть раньше начала")
        await state.update_data(end_time=end_time.isoformat())
        logger.debug(f"[{user_id}] Время окончания установлено: {end_time.isoformat()}")
        await message.answer(
            "🔌 Что будет недоступно во время работ?",
            reply_markup=create_cancel_keyboard()
        )
        await state.set_state(NewMessageStates.ENTER_UNAVAILABLE_SERVICES)
    except ValueError as e:
        logger.error(f"[{user_id}] Ошибка при парсинге времени окончания: {str(e)}", exc_info=True)
        await message.answer(
            "⏰ Введите корректное время окончания:\n"
            "• Формат: «дд.мм.гггг чч:мм»\n"
            "• Пример: «27.05.2025 16:00»",
            reply_markup=create_cancel_keyboard()
        )


@router.message(NewMessageStates.ENTER_UNAVAILABLE_SERVICES)
async def enter_unavailable_services(message: Message, state: FSMContext):
    """Обработчик ввода недоступных сервисов"""
    services = message.text.strip()
    user_id = message.from_user.id
    logger.info(f"[{user_id}] Введены недоступные сервисы: {services[:30]}...")
    if services == "❌ Отмена":
        logger.info(f"[{user_id}] Отмена на этапе ENTER_UNAVAILABLE_SERVICES")
        await state.clear()
        await message.answer("🚫 Действие отменено", reply_markup=create_main_keyboard())
        return
    await state.update_data(unavailable_services=services)
    data = await state.get_data()
    description = data.get("description", "")
    start_time = dt.fromisoformat(data["start_time"])
    end_time = dt.fromisoformat(data["end_time"])
    preview_text = (
        "📄 <b>Предварительный просмотр:</b>\n"
        f"🔧 <b>Регламентные работы</b>\n"
        f"• <b>Описание:</b> {description}\n"
        f"• <b>Начало:</b> {start_time.strftime(DATETIME_FORMAT)}\n"
        f"• <b>Конец:</b> {end_time.strftime(DATETIME_FORMAT)}\n"
        f"• <b>Недоступно:</b> {services}"
    )
    await state.update_data(preview_text=preview_text)
    from keyboards.alarm import create_petlocal_option_keyboard
    await message.answer(
        "📢 <b>Публикуем на Петлокале?</b>",
        parse_mode='HTML',
        reply_markup=create_petlocal_option_keyboard()
    )
    await state.set_state(NewMessageStates.SELECT_PETLOCAL_OPTION)


@router.callback_query(F.data.in_(["petlocal_publish", "petlocal_skip"]))
async def handle_petlocal_option_maintenance(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора публикации на Петлокале для регламентных работ"""
    user_id = callback.from_user.id
    
    if not await validate_callback_in(callback, ["petlocal_publish", "petlocal_skip"]):
        return
    
    publish_petlocal = callback.data == "petlocal_publish"
    logger.info(f"[{user_id}] Выбран вариант публикации на Петлокале: {publish_petlocal}")
    await state.update_data(publish_petlocal=publish_petlocal)
    
    # Получаем данные для предварительного просмотра
    data = await state.get_data()
    preview_text = data.get("preview_text", "")
    
    # Добавляем информацию о публикации на Петлокале в предпросмотр
    petlocal_option = "✅ Публикуем на Петлокале" if publish_petlocal else "❌ Не публикуем на Петлокале"
    if preview_text:
        preview_text += f"\n• <b>Петлокал:</b> {petlocal_option}"
    else:
        preview_text = f"📄 <b>Предварительный просмотр:</b>\n• <b>Петлокал:</b> {petlocal_option}"
    
    await state.update_data(preview_text=preview_text)
    
    # Показываем предварительный просмотр с кнопкой подтверждения
    result = await safe_edit_message(
        callback.message,
        preview_text,
        parse_mode='HTML',
        reply_markup=create_confirmation_keyboard()
    )
    if result is None:
        logger.warning(f"[{user_id}] Не удалось отредактировать сообщение, пробуем отправить новое")
        try:
            await callback.message.answer(
                preview_text,
                parse_mode='HTML',
                reply_markup=create_confirmation_keyboard()
            )
        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка при отправке предпросмотра: {e}", exc_info=True)
    await state.set_state(NewMessageStates.CONFIRMATION)
    await callback.answer()