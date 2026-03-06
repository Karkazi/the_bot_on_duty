"""
Обработчики для остановки событий (аварий и работ).
Содержит логику выбора типа события, выбора конкретного события и его остановки.
"""
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

from keyboards import (
    create_stop_type_keyboard,
    create_action_keyboard,
    create_alarm_selection_keyboard,
    create_maintenance_selection_keyboard,
    create_main_keyboard,
)
from utils.helpers import is_admin
from utils.callback_validator import validate_callback
from utils.channel_helpers import send_to_alarm_channels
from domain.states import StopStates
from bot_state import bot_state
from config import CONFIG
from services.simpleone_service import SimpleOneService

logger = logging.getLogger(__name__)
router = Router()


def format_alarm_info(alarm_id: str, alarm_info: dict) -> str:
    """
    Форматирует информацию о сбое для отображения.
    
    Args:
        alarm_id: ID сбоя
        alarm_info: Словарь с данными сбоя
    
    Returns:
        Отформатированная строка с информацией о сбое
    """
    try:
        fix_time_value = alarm_info.get("fix_time")
        if isinstance(fix_time_value, str):
            fix_time = datetime.fromisoformat(fix_time_value).strftime("%d.%m.%Y %H:%M")
        elif isinstance(fix_time_value, datetime):
            fix_time = fix_time_value.strftime("%d.%m.%Y %H:%M")
        else:
            fix_time = "неизвестно"
    except Exception as e:
        logger.warning(f"Ошибка форматирования времени сбоя {alarm_id}: {e}")
        fix_time = "неизвестно"
    
    author = alarm_info.get("user_id", "Неизвестен")
    issue = alarm_info.get("issue", "Без описания")
    
    text = (
        f"<b>🚨 Информация о сбое:</b>\n\n"
        f"• <b>ID:</b> <code>{alarm_id}</code>\n"
        f"• <b>👤 Автор:</b> {author}\n"
        f"• <b>🕒 Исправим до:</b> {fix_time}\n"
        f"• <b>🔧 Проблема:</b> {issue}\n\n"
        f"<b>Выберите действие:</b>"
    )
    return text


def format_maintenance_info(work_id: str, work_info: dict) -> str:
    """
    Форматирует информацию о работе для отображения.
    
    Args:
        work_id: ID работы
        work_info: Словарь с данными работы
    
    Returns:
        Отформатированная строка с информацией о работе
    """
    try:
        start_time_value = work_info.get("start_time")
        if isinstance(start_time_value, str):
            start_time = datetime.fromisoformat(start_time_value).strftime("%d.%m.%Y %H:%M")
        elif isinstance(start_time_value, datetime):
            start_time = start_time_value.strftime("%d.%m.%Y %H:%M")
        else:
            start_time = "неизвестно"
        
        end_time_value = work_info.get("end_time")
        if isinstance(end_time_value, str):
            end_time = datetime.fromisoformat(end_time_value).strftime("%d.%m.%Y %H:%M")
        elif isinstance(end_time_value, datetime):
            end_time = end_time_value.strftime("%d.%m.%Y %H:%M")
        else:
            end_time = "неизвестно"
    except Exception as e:
        logger.warning(f"Ошибка форматирования времени работы {work_id}: {e}")
        start_time = end_time = "неизвестно"
    
    description = work_info.get("description", "Нет описания")
    author = work_info.get("user_id", "Неизвестен")
    
    text = (
        f"<b>🔧 Информация о работе:</b>\n\n"
        f"• <b>ID:</b> <code>{work_id}</code>\n"
        f"• <b>👤 Автор:</b> {author}\n"
        f"• <b>⏰ Время:</b> {start_time} — {end_time}\n"
        f"• <b>📝 Описание:</b> {description}\n\n"
        f"<b>Выберите действие:</b>"
    )
    return text


@router.message(Command("manage"))
@router.message(F.text == "🛂 Управлять")
async def stop_selection(message: Message, state: FSMContext):
    """
    Обработчик команды управления событиями.
    
    Позволяет остановить или продлить активные аварии и регламентные работы.
    Требует прав администратора.
    """
    user_id = message.from_user.id
    logger.info(f"[{user_id}] Пользователь начал управление событиями")
    if not is_admin(user_id):
        logger.warning(f"[{user_id}] Пользователь не является админом — доступ запрещён")
        await message.answer(
            "❌ У вас нет прав для выполнения этой команды.\n"
            "Обратитесь к администратору для получения доступа.",
            parse_mode=ParseMode.HTML
        )
        return
    await state.clear()
    logger.info(f"[{user_id}] Очистка состояния завершена")
    await message.answer("Выберите тип события:", reply_markup=create_stop_type_keyboard())
    await state.set_state(StopStates.SELECT_TYPE)
    logger.info(f"[{user_id}] Перешёл в состояние SELECT_TYPE")


@router.callback_query(StopStates.SELECT_TYPE)
async def select_event_type(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора типа события через callback_query"""
    user_id = callback.from_user.id
    choice = callback.data  # Например: stop_type_alarm или stop_type_maintenance
    logger.info(f"[{user_id}] Пользователь выбрал тип события: {choice}")

    if choice == "cancel_action":
        logger.info(f"[{user_id}] Действие отменено пользователем")
        await state.clear()
        await callback.message.edit_text("🚫 Действие отменено", reply_markup=None)
        await callback.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
        await callback.answer()
        return

    elif choice == "stop_type_alarm":
        # Админы и суперадмины видят все сбои; остальные — только свои (логика в get_user_active_alarms)
        user_alarms = bot_state.get_user_active_alarms(user_id)
        logger.info(f"[{user_id}] Запрошены активные сбои (всего: %s)", len(user_alarms))
        if not user_alarms:
            logger.warning(f"[{user_id}] Нет активных сбоев")
            await callback.message.edit_text("❌ Нет активных сбоев", reply_markup=None)
            await callback.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await callback.answer()
            return
        keyboard = create_alarm_selection_keyboard(user_alarms)
        await state.update_data(type="alarm")
        logger.info(f"[{user_id}] Показаны доступные сбои")
        await callback.message.edit_text("Выберите сбой:", reply_markup=keyboard)
        await state.set_state(StopStates.SELECT_ITEM)
        logger.info(f"[{user_id}] Перешёл в состояние SELECT_ITEM")

    elif choice == "stop_type_maintenance":
        # Админы и суперадмины видят все работы; остальные — только свои (логика в get_user_active_maintenances)
        works_by_author = bot_state.get_user_active_maintenances(user_id)
        if not works_by_author:
            logger.warning(f"[{user_id}] Нет доступных работ")
            await callback.message.edit_text("❌ У вас нет активных работ", reply_markup=None)
            await callback.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await callback.answer()
            return
        keyboard = create_maintenance_selection_keyboard(works_by_author)
        await state.update_data(type="maintenance")
        logger.info(f"[{user_id}] Показаны доступные работы")
        await callback.message.edit_text("Выберите работу:", reply_markup=keyboard)
        await state.set_state(StopStates.SELECT_ITEM)
        logger.info(f"[{user_id}] Перешёл в состояние SELECT_ITEM")

    await callback.answer()


@router.callback_query(lambda call: call.data.startswith("select_"))
async def select_action(call: CallbackQuery, state: FSMContext):
    """Выбор конкретного события"""
    user_id = call.from_user.id
    
    if not await validate_callback(call, "select_"):
        return
    
    raw_data = call.data[7:]  # select_alarm_abc123 → alarm_abc123
    logger.info(f"[{user_id}] Получен callback: {call.data}")

    # Обработка кнопки "Отмена" в клавиатуре выбора
    if raw_data == "cancel":
        logger.info(f"[{user_id}] Выбор отменен пользователем")
        await state.clear()
        await call.message.edit_text("🚫 Выбор отменен", reply_markup=None)
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard(user_id))
        await call.answer()
        return

    try:
        parts = raw_data.split("_", 1)
        if len(parts) < 2:
            logger.warning(f"[{user_id}] Некорректный callback_data: {call.data}")
            await call.answer("❌ Неверные данные", show_alert=True)
            return

        data_type, item_id = parts
        
        # Валидация типа данных
        if data_type not in ["alarm", "maintenance", "no_alarms", "no_maintenances"]:
            logger.warning(f"[{user_id}] Неизвестный тип данных: {data_type}")
            await call.answer("❌ Неизвестный тип", show_alert=True)
            return
        logger.debug(f"[{user_id}] Тип: {data_type}, ID: {item_id}")

        if data_type == "alarm" and item_id == "no_alarms":
            logger.warning(f"[{user_id}] Пользователь попытался выбрать сбой, но их нет")
            await call.message.edit_text("❌ У вас нет активных сбоев", reply_markup=None)
            await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await state.clear()
            return

        elif data_type == "maintenance" and item_id == "no_maintenances":
            logger.warning(f"[{user_id}] Пользователь попытался выбрать работу, но их нет")
            await call.message.edit_text("❌ У вас нет активных работ", reply_markup=None)
            await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await state.clear()
            return

        if data_type == "alarm" and item_id not in bot_state.active_alarms:
            logger.warning(f"[{user_id}] Сбой {item_id} не найден")
            await call.answer("❌ Сбой не найден", show_alert=True)
            return
        elif data_type == "maintenance" and item_id not in bot_state.active_maintenances:
            logger.warning(f"[{user_id}] Работа {item_id} не найдена")
            await call.answer("❌ Работа не найдена", show_alert=True)
            return

        await state.update_data(data_type=data_type, item_id=item_id)
        logger.info(f"[{user_id}] Выбран {data_type}: {item_id}")
        
        # Формируем информацию о выбранном событии
        if data_type == "alarm":
            alarm_info = bot_state.active_alarms[item_id]
            info_text = format_alarm_info(item_id, alarm_info)
        elif data_type == "maintenance":
            maint_info = bot_state.active_maintenances[item_id]
            info_text = format_maintenance_info(item_id, maint_info)
        else:
            info_text = "Выберите действие:"
        
        await call.message.edit_text(info_text, reply_markup=create_action_keyboard(), parse_mode=ParseMode.HTML)
        await state.set_state(StopStates.SELECT_ACTION)
        logger.info(f"[{user_id}] Перешёл в состояние SELECT_ACTION")

    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при обработке callback: {str(e)}", exc_info=True)
        await call.answer("❌ Не удалось продолжить", show_alert=True)


@router.callback_query(StopStates.SELECT_ACTION)
async def handle_action_callback(call: CallbackQuery, state: FSMContext):
    """Обработка действия: Остановить / Продлить / Отмена"""
    action = call.data
    data = await state.get_data()
    data_type = data.get('data_type')
    item_id = data.get('item_id')
    logger.info(f"[{call.from_user.id}] Выбрано действие: {action} для {data_type}: {item_id}")

    if action == "action_cancel":
        logger.info(f"[{call.from_user.id}] Действие отменено пользователем")
        await state.clear()
        await call.message.edit_text("🚫 Действие отменено", reply_markup=None)
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard(call.from_user.id))
        await call.answer()
        return

    if action == "action_stop":
        logger.info(f"[{call.from_user.id}] Начата остановка {data_type}: {item_id}")
        if data_type == "alarm":
            from core.actions import stop_alarm
            async def reply_fn(t: str):
                await call.message.answer(t)
            success = await stop_alarm(item_id, call.bot, reply_fn)
            if not success:
                await call.answer("❌ Не удалось остановить сбой", show_alert=True)
                return
            logger.info(f"[{call.from_user.id}] Сбой {item_id} удалён из состояния")

        elif data_type == "maintenance":
            maint_info = bot_state.active_maintenances[item_id]

            if maint_info.get("publish_petlocal", True):
                try:
                    closed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
                    async with SimpleOneService() as simpleone:
                        html = simpleone.format_maintenance_closed_for_petlocal(
                            work_id=item_id,
                            description=maint_info.get("description", "не указано"),
                            closed_at=closed_at
                        )
                        result = await simpleone.create_portal_post(html)
                        if result.get("success"):
                            logger.info(f"[{call.from_user.id}] Пост о завершении работы {item_id} опубликован на Петлокале")
                        else:
                            error_msg = result.get("error", "Неизвестная ошибка")
                            logger.warning(f"[{call.from_user.id}] Не удалось опубликовать пост на Петлокале: {error_msg}")
                            if result.get("is_token_expired"):
                                await call.message.answer(
                                    "⚠️ <b>Не удалось опубликовать на Петлокале</b>\n\n"
                                    "🔑 <b>Токен SimpleOne устарел</b>\nТокены действительны 2 часа. Обновите токен в настройках бота.",
                                    parse_mode='HTML'
                                )
                except Exception as e:
                    logger.warning(f"[{call.from_user.id}] Ошибка при публикации на Петлокале: {e}", exc_info=True)

            del bot_state.active_maintenances[item_id]
            text = (
                f"✅ <b>Работа завершена</b>\n"
                f"• <b>Описание:</b> {maint_info['description']}"
            )
            if not await send_to_alarm_channels(call.bot, text):
                logger.error(f"[{call.from_user.id}] Не удалось отправить сообщение о завершении работы {item_id}")
            logger.info(f"[{call.from_user.id}] Работа {item_id} удалена из состояния")

        await call.message.edit_text(f"{('🚨 Сбой' if data_type == 'alarm' else '🔧 Работа')} {item_id} остановлен(а)")
        await bot_state.save_state()
        logger.info(f"[{call.from_user.id}] Бот сохранил обновлённое состояние")
        await state.clear()
        logger.info(f"[{call.from_user.id}] FSM очищена после остановки")
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())

    elif action == "action_extend":
        logger.info(f"[{call.from_user.id}] Начато продление {data_type}: {item_id}")
        if data_type == "alarm":
            from keyboards import create_extension_time_keyboard
            await call.message.edit_text("На сколько продлить сбой?", reply_markup=create_extension_time_keyboard())
            await state.set_state(StopStates.SELECT_ALARM_DURATION)
            logger.info(f"[{call.from_user.id}] Перешёл в состояние SELECT_ALARM_DURATION")
        elif data_type == "maintenance":
            # Предлагаем выбор способа ввода нового времени окончания
            await state.set_state(None)  # Сбрасываем состояние для обработки callback
            from keyboards import create_maintenance_extend_time_selection_keyboard
            await call.message.edit_text(
                "⏰ Выберите способ ввода нового времени окончания:",
                reply_markup=create_maintenance_extend_time_selection_keyboard()
            )
            logger.info(f"[{call.from_user.id}] Предложен выбор способа ввода времени для продления работы")

    await call.answer()
