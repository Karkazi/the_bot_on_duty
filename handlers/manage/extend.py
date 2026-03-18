"""
Обработчики для продления событий (аварий и работ).
Содержит логику выбора времени продления и обновления времени окончания.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from datetime import datetime as dt
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from keyboards import (
    create_extension_time_keyboard,
    create_cancel_keyboard,
    create_main_keyboard,
    create_maintenance_extend_time_selection_keyboard,
    create_month_keyboard,
)
from utils.helpers import parse_duration
from utils.channel_helpers import send_to_alarm_channels
from utils.validation import validate_datetime_format
from domain.states import StopStates, CalendarStates
from domain.constants import DATETIME_FORMAT
from bot_state import bot_state
from config import CONFIG

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(StopStates.SELECT_ALARM_DURATION)
async def handle_alarm_extension_callback(call: CallbackQuery, state: FSMContext):
    """Продление сбоя на определённое время"""
    duration = call.data
    data = await state.get_data()
    item_id = data['item_id']
    logger.info(f"[{call.from_user.id}] Выбрано продление сбоя {item_id} на {duration}")

    alarm = bot_state.active_alarms.get(item_id)
    if not alarm:
        logger.warning(f"[{call.from_user.id}] Сбой {item_id} не найден")
        await call.message.edit_text("❌ Сбой не найден", reply_markup=None)
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
        await call.answer()
        return

    fix_time_value = alarm.get("fix_time")
    old_end = None

    if isinstance(fix_time_value, str):
        try:
            old_end = datetime.fromisoformat(fix_time_value)
        except ValueError:
            logger.error(f"[{call.from_user.id}] Неверный формат времени у сбоя {item_id}")
            await call.message.edit_text("❌ Неверный формат времени", reply_markup=None)
            await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await call.answer()
            return
    elif isinstance(fix_time_value, datetime):
        old_end = fix_time_value
    else:
        logger.warning(f"[{call.from_user.id}] Некорректное значение fix_time для сбоя {item_id}")
        await call.message.edit_text("❌ Некорректное время завершения", reply_markup=None)
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
        await call.answer()
        return

    delta = None
    if duration == "extend_30_min":
        delta = timedelta(minutes=30)
        logger.info(f"[{call.from_user.id}] Продление: +30 мин")
    elif duration == "extend_1_hour":
        delta = timedelta(hours=1)
        logger.info(f"[{call.from_user.id}] Продление: +1 час")
    elif duration == "extend_manual":
        # Переход к ручному вводу длительности
        logger.info(f"[{call.from_user.id}] Выбран ручной ввод длительности продления")
        await state.update_data(manual_input_attempts=0)
        await call.message.edit_text(
            "✏️ Введите длительность продления (например: 1 час, 30 минут, 2 часа, 15 минут):",
            reply_markup=create_cancel_keyboard()
        )
        await state.set_state(StopStates.ENTER_ALARM_DURATION_MANUAL)
        await call.answer()
        return
    elif duration == "extend_cancel":
        logger.info(f"[{call.from_user.id}] Продление отменено пользователем")
        await state.clear()
        await call.message.edit_text("🚫 Продление отменено", reply_markup=None)
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
        await call.answer()
        return
    else:
        logger.warning(f"[{call.from_user.id}] Некорректный выбор: {duration}")
        await call.answer("⚠️ Некорректный выбор", show_alert=True)
        return

    new_end = old_end + delta
    alarm["fix_time"] = new_end.isoformat()
    # Сбрасываем флаг напоминания при продлении
    if "reminder_sent_for" in alarm:
        del alarm["reminder_sent_for"]
    logger.info(f"[{call.from_user.id}] Новое время завершения: {new_end.isoformat()}, флаг напоминания сброшен")

    text = (
        f"🔄 <b>Сбой продлён</b>\n"
        f"• <b>Проблема:</b> {alarm['issue']}\n"
        f"• <b>Новое время окончания:</b> {new_end.strftime('%d.%m.%Y %H:%M')}"
    )
    async def _send():
        try:
            ok = await send_to_alarm_channels(call.bot, text)
            if not ok:
                logger.error(f"[{call.from_user.id}] Не удалось отправить сообщение о продлении сбоя")
            else:
                logger.info(f"[{call.from_user.id}] Сообщение о продлении отправлено в канал")
        except Exception as e:
            logger.warning(f"[{call.from_user.id}] Каналы при продлении сбоя: %s", e, exc_info=True)
    asyncio.create_task(_send())

    await call.message.edit_text(f"🕒 Сбой {item_id} продлён до {new_end.strftime('%d.%m.%Y %H:%M')}", reply_markup=None)
    await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
    await bot_state.save_state()
    logger.info(f"[{call.from_user.id}] Сохранено обновлённое состояние")
    await state.clear()
    logger.info(f"[{call.from_user.id}] FSM очищена после продления")
    await call.answer()


@router.message(StopStates.ENTER_ALARM_DURATION_MANUAL)
async def handle_alarm_duration_manual(message: Message, state: FSMContext):
    """Обработчик ручного ввода длительности продления сбоя"""
    user_id = message.from_user.id
    duration_text = message.text.strip()
    
    # Проверка на отмену
    if duration_text == "❌ Отмена":
        await state.clear()
        await message.answer("🚫 Ввод отменён", reply_markup=create_main_keyboard())
        return
    
    # Получаем данные из состояния (включая счетчик попыток)
    data = await state.get_data()
    attempts = data.get('manual_input_attempts', 0)
    
    # Парсим длительность
    delta = parse_duration(duration_text)
    
    if delta is None:
        attempts += 1
        await state.update_data(manual_input_attempts=attempts)
        
        # Если попыток >= 3, сбрасываем процесс и возвращаем в главное меню
        if attempts >= 3:
            logger.warning(f"[{user_id}] Превышено количество попыток ввода длительности ({attempts})")
            await state.clear()
            await message.answer(
                "❌ Превышено количество попыток ввода (3 попытки).\n"
                "Процесс отменён. Возврат в главное меню.",
                reply_markup=create_main_keyboard()
            )
            return
        
        # Показываем сообщение об ошибке с количеством оставшихся попыток
        remaining_attempts = 3 - attempts
        await message.answer(
            f"❌ Не удалось распознать длительность. Осталось попыток: {remaining_attempts}\n\n"
            "Попробуйте ввести, например:\n"
            "• 1 час\n"
            "• 30 минут\n"
            "• 2 часа\n"
            "• 15 минут\n"
            "• 1.5 часа",
            reply_markup=create_cancel_keyboard()
        )
        return
    
    # Если дошли сюда, значит парсинг успешен
    await state.update_data(manual_input_attempts=0)
    
    # Может быть item_id (из меню управления) или alarm_id (из напоминания)
    item_id = data.get('item_id') or data.get('alarm_id')
    
    if not item_id:
        logger.warning(f"[{user_id}] Не найден item_id или alarm_id в состоянии")
        await state.clear()
        await message.answer("❌ Ошибка: не найден ID сбоя", reply_markup=create_main_keyboard())
        return
    
    alarm = bot_state.active_alarms.get(item_id)
    if not alarm:
        logger.warning(f"[{user_id}] Сбой {item_id} не найден")
        await state.clear()
        await message.answer("❌ Сбой не найден", reply_markup=create_main_keyboard())
        return
    
    # Получаем текущее время окончания
    fix_time_value = alarm.get("fix_time")
    if isinstance(fix_time_value, str):
        try:
            old_end = datetime.fromisoformat(fix_time_value)
        except ValueError:
            logger.error(f"[{user_id}] Неверный формат времени у сбоя {item_id}")
            await state.clear()
            await message.answer("❌ Неверный формат времени", reply_markup=create_main_keyboard())
            return
    elif isinstance(fix_time_value, datetime):
        old_end = fix_time_value
    else:
        logger.warning(f"[{user_id}] Некорректное значение fix_time для сбоя {item_id}")
        await state.clear()
        await message.answer("❌ Некорректное время завершения", reply_markup=create_main_keyboard())
        return
    
    # Вычисляем новое время
    new_end = old_end + delta
    alarm["fix_time"] = new_end.isoformat()
    
    # Сбрасываем флаг напоминания при продлении
    if "reminder_sent_for" in alarm:
        del alarm["reminder_sent_for"]
    
    logger.info(f"[{user_id}] Сбой {item_id} продлён на {delta} (вручную), новое время: {new_end.isoformat()}")
    
    text = (
        f"🔄 <b>Сбой продлён</b>\n"
        f"• <b>Проблема:</b> {alarm['issue']}\n"
        f"• <b>Новое время окончания:</b> {new_end.strftime('%d.%m.%Y %H:%M')}"
    )
    async def _send():
        try:
            ok = await send_to_alarm_channels(message.bot, text)
            if not ok:
                logger.error(f"[{user_id}] Не удалось отправить сообщение о продлении сбоя")
            else:
                logger.info(f"[{user_id}] Сообщение о продлении отправлено в канал")
        except Exception as e:
            logger.warning(f"[{user_id}] Каналы при продлении сбоя: %s", e, exc_info=True)
    asyncio.create_task(_send())

    await message.answer(
        f"✅ Сбой {item_id} продлён до {new_end.strftime('%d.%m.%Y %H:%M')}",
        reply_markup=create_main_keyboard()
    )
    await bot_state.save_state()
    await state.clear()


@router.message(StopStates.ENTER_MAINTENANCE_END)
async def handle_maintenance_new_end(message: Message, state: FSMContext):
    """Продление работы на новое время"""
    new_time_str = message.text.strip()
    data = await state.get_data()
    item_id = data['item_id']
    logger.info(f"[{message.from_user.id}] Введено новое время: {new_time_str}")

    maint = bot_state.active_maintenances.get(item_id)
    if not maint:
        logger.warning(f"[{message.from_user.id}] Работа {item_id} не найдена")
        await message.answer("❌ Работа не найдена")
        return

    # Валидация формата даты
    is_valid, error_msg = validate_datetime_format(new_time_str, DATETIME_FORMAT)
    if not is_valid:
        logger.warning(f"[{message.from_user.id}] Неверный формат даты: {new_time_str}")
        await message.answer(error_msg)
        return
    
    try:
        new_time = datetime.strptime(new_time_str, DATETIME_FORMAT)
        # Обновляем оба возможных поля для совместимости
        if "end_time" in maint:
            maint["end_time"] = new_time.isoformat()
        if "end" in maint:
            maint["end"] = new_time.isoformat()
        # Сбрасываем флаг напоминания при продлении
        if "reminder_sent_for" in maint:
            del maint["reminder_sent_for"]
        logger.info(f"[{message.from_user.id}] Новое время установлено: {new_time.isoformat()}, флаг напоминания сброшен")

        text = (
            f"🔄 <b>Работа продлена</b>\n"
            f"• <b>Описание:</b> {maint['description']}\n"
            f"• <b>Новое время окончания:</b> {new_time.strftime(DATETIME_FORMAT)}"
        )
        async def _send():
            try:
                ok = await send_to_alarm_channels(message.bot, text)
                if not ok:
                    logger.error(f"[{message.from_user.id}] Не удалось отправить сообщение о продлении работы")
                else:
                    logger.info(f"[{message.from_user.id}] Сообщение о продлении работы отправлено в канал")
            except Exception as e:
                logger.warning(f"[{message.from_user.id}] Каналы при продлении работы: %s", e, exc_info=True)
        asyncio.create_task(_send())

        await message.answer(f"🕒 Работа {item_id} продлена до {new_time.strftime(DATETIME_FORMAT)}")
        await bot_state.save_state()
        logger.info(f"[{message.from_user.id}] Сохранено обновлённое состояние")
        await state.clear()
        logger.info(f"[{message.from_user.id}] FSM очищена после продления")
        await message.answer("Выберите действие:", reply_markup=create_main_keyboard())

    except ValueError as e:
        logger.error(f"[{message.from_user.id}] Ошибка парсинга даты: {e}", exc_info=True)
        await message.answer("❌ Неверный формат даты. Используйте: dd.mm.yyyy hh:mm")


@router.callback_query(F.data == "maint_extend_spinners")
async def handle_extend_spinners_from_manage(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора спиннеров при продлении работ"""
    from handlers.maintenance_spinners import start_extend_spinners
    await start_extend_spinners(call, state)


@router.callback_query(F.data == "maint_extend_text")
async def handle_extend_text_from_manage(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора текстового ввода при продлении работ"""
    from handlers.maintenance_spinners import handle_extend_text_method
    await handle_extend_text_method(call, state)


@router.callback_query(F.data == "maint_extend_calendar")
async def handle_extend_calendar_from_manage(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора календаря при продлении работ"""
    user_id = call.from_user.id
    logger.info(f"[{user_id}] Выбран способ ввода времени: календарь (продление)")
    
    data = await state.get_data()
    # Может быть item_id (из меню управления) или work_id (из напоминания)
    item_id = data.get('item_id') or data.get('work_id')
    
    if not item_id:
        await call.answer("❌ Ошибка: не найден ID работы", show_alert=True)
        return
    
    maint = bot_state.active_maintenances.get(item_id)
    if not maint:
        await call.answer("❌ Работа не найдена", show_alert=True)
        return
    
    # Получаем текущее время окончания для определения года
    end_time_str = maint.get("end_time")
    if isinstance(end_time_str, str):
        end_time = dt.fromisoformat(end_time_str)
    elif isinstance(end_time_str, dt):
        end_time = end_time_str
    else:
        await call.answer("❌ Ошибка: некорректное время окончания", show_alert=True)
        return
    
    # Используем календарь для выбора даты окончания
    current_year = end_time.year
    await state.update_data(end_year=current_year, field_type="end", item_id=item_id)
    await state.set_state(CalendarStates.SELECT_MONTH)
    await call.message.edit_text(
        "📅 Выберите месяц нового времени окончания работ:",
        reply_markup=create_month_keyboard(current_year, "end")
    )
    await call.answer()
