"""
Обработчики календаря для выбора даты и времени.
Содержит логику выбора месяца, дня, часа и минуты для аварий и работ.
"""
import asyncio
import logging
from datetime import datetime as dt
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from keyboards import (
    create_month_keyboard,
    create_day_keyboard,
    create_hour_keyboard,
    create_minute_keyboard,
    create_main_keyboard,
)
from utils.callback_validator import validate_callback
from domain.states import CalendarStates
from domain.constants import DATETIME_FORMAT
from bot_state import bot_state
from config import CONFIG
from utils.channel_helpers import send_to_alarm_channels

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "maint_method_calendar")
async def handle_calendar_method(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора календаря для ввода времени работ"""
    user_id = call.from_user.id
    logger.info(f"[{user_id}] Выбран способ ввода времени: календарь")
    
    # Используем календарь для выбора даты
    current_year = dt.now().year
    await state.update_data(start_year=current_year, field_type="start")
    await state.set_state(CalendarStates.SELECT_MONTH)
    await call.message.edit_text(
        "📅 Выберите месяц начала работ:",
        reply_markup=create_month_keyboard(current_year, "start")
    )
    await call.answer()


@router.callback_query(F.data.startswith("cal_month_"))
async def select_month(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора месяца"""
    user_id = call.from_user.id
    try:
        # Парсим: cal_month_{field_prefix}_{year}_{month}
        parts = call.data.split("_")
        if len(parts) != 5:
            raise ValueError("Неверный формат callback_data")
        field_prefix = parts[2]
        year = int(parts[3])
        month = int(parts[4])
        
        await state.update_data(**{f"{field_prefix}_year": year, f"{field_prefix}_month": month})
        await state.set_state(CalendarStates.SELECT_DAY)
        await call.message.edit_text(
            f"📅 Выберите день ({year}, {['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'][month-1]}):",
            reply_markup=create_day_keyboard(year, month, field_prefix)
        )
        await call.answer()
    except (ValueError, IndexError) as e:
        logger.error(f"[{user_id}] Ошибка обработки выбора месяца: {e}")
        await call.answer("❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data.startswith("cal_day_"))
async def select_day(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора дня"""
    user_id = call.from_user.id
    try:
        # Парсим: cal_day_{field_prefix}_{year}_{month}_{day}
        parts = call.data.split("_")
        if len(parts) != 6:
            raise ValueError("Неверный формат callback_data")
        field_prefix = parts[2]
        year = int(parts[3])
        month = int(parts[4])
        day = int(parts[5])
        
        await state.update_data(**{f"{field_prefix}_day": day})
        await state.set_state(CalendarStates.SELECT_HOUR)
        await call.message.edit_text(
            f"⏰ Выберите час ({day:02d}.{month:02d}.{year}):",
            reply_markup=create_hour_keyboard(field_prefix)
        )
        await call.answer()
    except (ValueError, IndexError) as e:
        logger.error(f"[{user_id}] Ошибка обработки выбора дня: {e}")
        await call.answer("❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data.startswith("cal_hour_"))
async def select_hour(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора часа"""
    user_id = call.from_user.id
    try:
        # Парсим: cal_hour_{field_prefix}_{hour}
        parts = call.data.split("_")
        if len(parts) != 4:
            raise ValueError("Неверный формат callback_data")
        field_prefix = parts[2]
        hour = int(parts[3])
        
        await state.update_data(**{f"{field_prefix}_hour": hour})
        await state.set_state(CalendarStates.SELECT_MINUTE)
        await call.message.edit_text(
            f"⏰ Выберите минуты (час: {hour:02d}):",
            reply_markup=create_minute_keyboard(field_prefix)
        )
        await call.answer()
    except (ValueError, IndexError) as e:
        logger.error(f"[{user_id}] Ошибка обработки выбора часа: {e}")
        await call.answer("❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data.startswith("cal_minute_"))
async def select_minute(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора минуты - завершает выбор времени"""
    user_id = call.from_user.id
    try:
        # Парсим: cal_minute_{field_prefix}_{minute}
        parts = call.data.split("_")
        if len(parts) != 4:
            raise ValueError("Неверный формат callback_data")
        field_prefix = parts[2]
        minute = int(parts[3])
        
        data = await state.get_data()
        year = data.get(f"{field_prefix}_year")
        month = data.get(f"{field_prefix}_month")
        day = data.get(f"{field_prefix}_day")
        hour = data.get(f"{field_prefix}_hour")
        
        if not all([year, month, day, hour is not None]):
            raise ValueError("Не все данные времени заполнены")
        
        # Создаем datetime объект
        selected_time = dt(year, month, day, hour, minute)
        
        # Валидация: для start_time проверяем, что не в прошлом
        if field_prefix == "start":
            now = dt.now()
            if selected_time < now:
                await call.message.edit_text(
                    "⚠️ Время начала не может быть в прошлом.\n"
                    "Выберите другое время:",
                    reply_markup=create_month_keyboard(year, field_prefix)
                )
                await state.set_state(CalendarStates.SELECT_MONTH)
                await call.answer("❌ Время в прошлом", show_alert=True)
                return
            
            await state.update_data(start_time=selected_time.isoformat())
            logger.info(f"[{user_id}] Время начала установлено: {selected_time.isoformat()}")
            
            # Переходим к выбору времени окончания
            await state.update_data(end_year=year, field_type="end")
            await state.set_state(CalendarStates.SELECT_MONTH)
            await call.message.edit_text(
                f"📅 Время начала: {selected_time.strftime(DATETIME_FORMAT)}\n"
                f"Выберите месяц окончания работ:",
                reply_markup=create_month_keyboard(year, "end")
            )
        
        elif field_prefix == "end":
            # Проверяем, это продление работ или создание новых
            item_id = data.get("item_id")
            
            if item_id:
                # Это продление работ
                maint = bot_state.active_maintenances.get(item_id)
                if not maint:
                    await call.message.edit_text("❌ Работа не найдена", reply_markup=None)
                    await call.answer()
                    await state.clear()
                    return
                
                # Валидация: новое время должно быть позже текущего времени окончания
                end_time_str = maint.get("end_time")
                if isinstance(end_time_str, str):
                    old_end_time = dt.fromisoformat(end_time_str)
                elif isinstance(end_time_str, dt):
                    old_end_time = end_time_str
                else:
                    await call.message.edit_text("❌ Ошибка: некорректное время окончания", reply_markup=None)
                    await call.answer()
                    await state.clear()
                    return
                
                if selected_time <= old_end_time:
                    await call.message.edit_text(
                        f"⚠️ Новое время окончания должно быть позже текущего ({old_end_time.strftime(DATETIME_FORMAT)}).\n"
                        f"Выберите другое время:",
                        reply_markup=create_month_keyboard(year, field_prefix)
                    )
                    await state.set_state(CalendarStates.SELECT_MONTH)
                    await call.answer("❌ Новое время раньше текущего", show_alert=True)
                    return
                
                # Обновляем время окончания
                maint["end_time"] = selected_time.isoformat()
                # Сбрасываем флаг напоминания при продлении
                if "reminder_sent_for" in maint:
                    del maint["reminder_sent_for"]
                
                logger.info(f"[{user_id}] Время окончания работы {item_id} изменено через календарь: {selected_time.isoformat()}")
                
                text = (
                    f"🔄 <b>Работа продлена</b>\n"
                    f"• <b>Описание:</b> {maint['description']}\n"
                    f"• <b>Новое время окончания:</b> {selected_time.strftime(DATETIME_FORMAT)}"
                )
                async def _send():
                    try:
                        ok = await send_to_alarm_channels(call.bot, text)
                        if not ok:
                            logger.error(f"[{user_id}] Не удалось отправить сообщение о продлении работы")
                        else:
                            logger.info(f"[{user_id}] Сообщение о продлении работы отправлено в канал")
                    except Exception as e:
                        logger.warning(f"[{user_id}] Каналы при продлении: %s", e, exc_info=True)
                asyncio.create_task(_send())
                
                # Сохраняем состояние
                await bot_state.save_state()
                
                # Уведомляем пользователя
                await call.message.edit_text(
                    f"✅ Работа {item_id} продлена до {selected_time.strftime(DATETIME_FORMAT)}",
                    reply_markup=None
                )
                await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
                
                # Очищаем FSM состояние
                await state.clear()
                await call.answer()
                return
            
            # Это создание новых работ
            # Валидация: конец должен быть позже начала
            start_time_str = data.get("start_time")
            if not start_time_str:
                await call.message.edit_text("❌ Ошибка: время начала не установлено", reply_markup=None)
                await call.answer()
                await state.clear()
                return
            
            start_time = dt.fromisoformat(start_time_str) if isinstance(start_time_str, str) else start_time_str
            if selected_time <= start_time:
                await call.message.edit_text(
                    f"⚠️ Время окончания должно быть позже времени начала ({start_time.strftime(DATETIME_FORMAT)}).\n"
                    f"Выберите другое время:",
                    reply_markup=create_month_keyboard(year, field_prefix)
                )
                await state.set_state(CalendarStates.SELECT_MONTH)
                await call.answer("❌ Время окончания раньше начала", show_alert=True)
                return
            
            await state.update_data(end_time=selected_time.isoformat())
            logger.info(f"[{user_id}] Время окончания установлено: {selected_time.isoformat()}")
            
            # Переходим к вводу недоступных сервисов
            from domain.states import NewMessageStates
            await state.set_state(NewMessageStates.ENTER_UNAVAILABLE_SERVICES)
            await call.message.edit_text(
                f"📅 Время работ: {start_time.strftime(DATETIME_FORMAT)} - {selected_time.strftime(DATETIME_FORMAT)}\n"
                f"Укажите недоступные сервисы:",
                reply_markup=None
            )
        
        await call.answer()
    except (ValueError, IndexError) as e:
        logger.error(f"[{user_id}] Ошибка обработки выбора минуты: {e}")
        await call.answer("❌ Ошибка обработки", show_alert=True)
