"""
Обработчики для напоминаний о событиях.
Содержит логику проверки напоминаний, обработки действий из напоминаний и автоматического закрытия по Jira.
"""
import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from keyboards import (
    create_extension_time_keyboard,
    create_main_keyboard,
    create_cancel_keyboard,
)
from utils.helpers import parse_duration
from utils.channel_helpers import send_to_alarm_channels
from utils.jira_status_checker import get_jira_issue_status
from domain.states import ReminderStates, StopStates
from domain.constants import DATETIME_FORMAT, JIRA_STATUS_FIXED, JIRA_STATUS_FIXED_EN, JIRA_STATUS_FIXED_RU, JIRA_STATUS_CHECK_INTERVAL
from bot_state import bot_state
from config import jira_browse_url
from .scm import handle_scm_alarm_close
from services.simpleone_service import SimpleOneService

logger = logging.getLogger(__name__)
router = Router()


async def check_reminders(bot: Bot):
    """
    Оптимизированная фоновая задача для проверки напоминаний.
    Использует ReminderService для разделения ответственности.
    """
    from services.reminder_service import ReminderService
    
    reminder_service = ReminderService(bot_state)
    
    while True:
        try:
            now = datetime.now()
            logger.debug(f"[REMINDER] Проверка уведомлений. Текущее время: {now.isoformat()}")
            
            # Оптимизация: создаем snapshot списка items вместо копирования всего словаря
            alarms_snapshot = dict(bot_state.active_alarms)
            maintenances_snapshot = dict(bot_state.active_maintenances)
            
            # Используем сервис для проверки напоминаний
            alarm_reminders = await reminder_service.check_alarm_reminders(bot, alarms_snapshot)
            maintenance_reminders = await reminder_service.check_maintenance_reminders(bot, maintenances_snapshot)
            closed_by_jira = await reminder_service.check_jira_statuses(bot, alarms_snapshot)
            
            if alarm_reminders > 0 or maintenance_reminders > 0 or closed_by_jira > 0:
                logger.info(
                    f"[REMINDER] Отправлено напоминаний: аварии={alarm_reminders}, "
                    f"работы={maintenance_reminders}, закрыто по Jira={closed_by_jira}"
                )

        except Exception as e:
            # Критическая ошибка в цикле - логируем и продолжаем
            logger.critical(f"[REMINDER] Критическая ошибка в цикле проверки напоминаний: {e}", exc_info=True)

        await asyncio.sleep(60)  # Проверяем каждую минуту


async def auto_close_alarm_by_jira_status(bot: Bot, alarm_id: str, alarm: dict, jira_key: str):
    """
    Автоматически закрывает сбой при изменении статуса в Jira на "Failure Fixed".
    
    Args:
        bot: Экземпляр бота
        alarm_id: ID сбоя в боте
        alarm: Данные сбоя
        jira_key: Ключ задачи в Jira
    """
    import asyncio
    text = f"✅ Сбой устранён\n• Проблема: {alarm.get('issue', 'не указано')}"

    async def _task_scm():
        try:
            await handle_scm_alarm_close(bot, alarm_id, alarm)
        except Exception as e:
            logger.warning(f"[AUTO_CLOSE] SCM для {alarm_id}: {e}", exc_info=True)

    async def _task_petlocal():
        if not alarm.get("publish_petlocal", True):
            return
        try:
            closed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
            async with SimpleOneService() as simpleone:
                html = simpleone.format_alarm_closed_for_petlocal(
                    alarm_id=alarm_id, issue=alarm.get("issue", "не указано"), closed_at=closed_at
                )
                result = await simpleone.create_portal_post(html)
                if result.get("success"):
                    logger.info(f"[AUTO_CLOSE] Пост о закрытии сбоя {alarm_id} опубликован на Петлокале")
                else:
                    logger.warning(f"[AUTO_CLOSE] Петлокал для {alarm_id}: {result.get('error', '')}")
        except Exception as e:
            logger.warning(f"[AUTO_CLOSE] Петлокал для {alarm_id}: {e}", exc_info=True)

    async def _task_channels():
        try:
            ok = await send_to_alarm_channels(bot, text)
            if ok:
                logger.info(f"[AUTO_CLOSE] Сообщение об устранении сбоя {alarm_id} отправлено в канал")
            else:
                logger.error(f"[AUTO_CLOSE] Не удалось отправить в канал для сбоя {alarm_id}")
        except Exception as e:
            logger.warning(f"[AUTO_CLOSE] Каналы для {alarm_id}: {e}", exc_info=True)

    await asyncio.gather(_task_scm(), _task_petlocal(), _task_channels())

    del bot_state.active_alarms[alarm_id]
    logger.info(f"[AUTO_CLOSE] Сбой {alarm_id} автоматически закрыт по статусу Jira")
    await bot_state.save_state()


@router.callback_query(F.data.in_(["reminder_extend", "reminder_stop"]))
async def handle_reminder_action(call: CallbackQuery, state: FSMContext):
    """Обработка действий из уведомления о сбое"""
    user_id = call.from_user.id
    
    # Пропускаем напоминания о работах (они обрабатываются отдельным обработчиком)
    if "maintenance" in call.data:
        return
    
    action = call.data.split("_", 1)[1]  # "stop" или "extend"
    
    # Валидация действия
    if action not in ["stop", "extend"]:
        logger.warning(f"[{user_id}] Неизвестное действие напоминания: {action}")
        await call.answer("❌ Неизвестное действие", show_alert=True)
        return
    user_state = bot_state.user_states.get(user_id)

    logger.info(f"[{user_id}] Нажата кнопка напоминания: {action}")

    if not user_state or user_state.get("type") != "reminder":
        logger.warning(f"[{user_id}] Уведомление устарело или не существует")
        await call.answer("❌ Это уведомление устарело")
        return

    alarm_id = user_state["alarm_id"]
    alarm = bot_state.active_alarms.get(alarm_id)

    if not alarm:
        logger.warning(f"[{user_id}] Сбой {alarm_id} не найден при обработке напоминания")
        await call.message.edit_text("❌ Сбой уже устранен", reply_markup=None)
        if user_id in bot_state.user_states:
            del bot_state.user_states[user_id]
        await call.answer()
        return

    if action == "stop":
        logger.info(f"[{user_id}] Сбой {alarm_id} остановлен по напоминанию")

        async def _reply_fn(_text: str):
            """Ответ пользователю при остановке по напоминанию — не дублируем, UI обновим ниже."""
            pass

        # Единая логика остановки: чат MAX (архив в Jira + очистка), SCM, Петлокал, каналы, удаление из состояния
        from core.actions import stop_alarm
        ok = await stop_alarm(alarm_id, call.bot, _reply_fn)
        if not ok:
            await call.answer("❌ Сбой не найден или уже устранён", show_alert=True)
            return

        await call.message.edit_text("🚫 Сбой устранен по решению автора", reply_markup=None)
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
        if user_id in bot_state.user_states:
            del bot_state.user_states[user_id]
        logger.info(f"[{user_id}] Сбой {alarm_id} остановлен через напоминание")

    elif action == "extend":
        logger.info(f"[{user_id}] Запрошено продление сбоя {alarm_id}")
        await call.message.edit_text("На сколько продлить сбой?", reply_markup=create_extension_time_keyboard())
        await state.update_data(alarm_id=alarm_id)
        await state.set_state(ReminderStates.WAITING_FOR_EXTENSION)
        logger.info(f"[{user_id}] Перешёл в состояние WAITING_FOR_EXTENSION")

    await call.answer()


@router.callback_query(F.data.in_(["reminder_extend_maintenance", "reminder_stop_maintenance"]))
async def handle_maintenance_reminder_action(call: CallbackQuery, state: FSMContext):
    """Обработка действий из напоминания о работе"""
    user_id = call.from_user.id
    
    # Парсим действие из callback_data
    if call.data == "reminder_extend_maintenance":
        action = "extend"
    elif call.data == "reminder_stop_maintenance":
        action = "stop"
    else:
        logger.error(f"[{user_id}] Неожиданный callback_data для напоминания работы: {call.data}")
        await call.answer("❌ Неизвестное действие", show_alert=True)
        return
    
    user_state = bot_state.user_states.get(user_id)
    
    logger.info(f"[{user_id}] Нажата кнопка напоминания работы: {action}")
    
    if not user_state or user_state.get("type") != "maintenance_reminder":
        logger.warning(f"[{user_id}] Уведомление о работе устарело или не существует")
        await call.answer("❌ Это уведомление устарело")
        return
    
    work_id = user_state["work_id"]
    work = bot_state.active_maintenances.get(work_id)
    
    if not work:
        logger.warning(f"[{user_id}] Работа {work_id} не найдена при обработке напоминания")
        await call.message.edit_text("❌ Работа уже завершена", reply_markup=None)
        if user_id in bot_state.user_states:
            del bot_state.user_states[user_id]
        await call.answer()
        return
    
    if action == "stop":
        logger.info(f"[{user_id}] Работа {work_id} завершена по напоминанию")
        from core.actions import stop_maintenance
        async def _reply_fn(t: str):
            pass  # UI обновим ниже
        ok = await stop_maintenance(work_id, call.bot, _reply_fn)
        if not ok:
            await call.message.edit_text("❌ Работа не найдена", reply_markup=None)
            await call.answer()
            return
        await call.message.edit_text("🚫 Работа завершена по решению автора", reply_markup=None)
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
        if user_id in bot_state.user_states:
            del bot_state.user_states[user_id]
        await bot_state.save_state()
        logger.info(f"[{user_id}] Работа {work_id} завершена через напоминание")
    
    elif action == "extend":
        logger.info(f"[{user_id}] Запрошено продление работы {work_id}")
        await call.message.edit_text("На сколько продлить работу?", reply_markup=create_extension_time_keyboard())
        await state.update_data(work_id=work_id)
        await state.set_state(ReminderStates.WAITING_FOR_EXTENSION)
        logger.info(f"[{user_id}] Перешёл в состояние WAITING_FOR_EXTENSION для работы")
    
    await call.answer()


@router.callback_query(ReminderStates.WAITING_FOR_EXTENSION)
async def handle_reminder_extension(call: CallbackQuery, state: FSMContext):
    """Продление сбоя или работы из напоминания"""
    duration = call.data
    data = await state.get_data()
    
    # Проверяем, есть ли work_id (для работ) или alarm_id (для сбоев)
    work_id = data.get("work_id")
    alarm_id = data.get("alarm_id")
    
    if work_id:
        # Продление работы
        work = bot_state.active_maintenances.get(work_id)
        if not work:
            logger.warning(f"[{call.from_user.id}] Работа {work_id} не найдена при продлении")
            await call.message.edit_text("❌ Работа не найдена", reply_markup=None)
            await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await call.answer()
            return
        
        logger.info(f"[{call.from_user.id}] Выбрано продление работы {work_id}: {duration}")
        
        # Обработка кнопки "Указать вручную" для работ
        if duration == "extend_manual":
            if not work_id:
                work_id = data.get('item_id')
            if work_id:
                await state.update_data(item_id=work_id)
            from handlers.maintenance_spinners import start_extend_spinners
            await start_extend_spinners(call, state)
            await call.answer()
            return
        elif duration == "extend_cancel":
            logger.info(f"[{call.from_user.id}] Продление работы отменено")
            await state.clear()
            await call.message.edit_text("🚫 Продление отменено", reply_markup=None)
            await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await call.answer()
            return
        
        # Получаем текущее время окончания
        end_time_value = work.get("end_time") or work.get("end")
        if isinstance(end_time_value, str):
            old_end = datetime.fromisoformat(end_time_value)
        elif isinstance(end_time_value, datetime):
            old_end = end_time_value
        else:
            logger.error(f"[{call.from_user.id}] Некорректное значение end_time для работы {work_id}")
            await call.message.edit_text("❌ Некорректное время окончания", reply_markup=None)
            await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await call.answer()
            return
        
        delta = timedelta(minutes=30) if duration == "extend_30_min" else timedelta(hours=1)
        new_end = old_end + delta
        
        # Обновляем время окончания
        if "end_time" in work:
            work["end_time"] = new_end.isoformat()
        if "end" in work:
            work["end"] = new_end.isoformat()
        
        # Сбрасываем флаг напоминания при продлении
        if "reminder_sent_for" in work:
            del work["reminder_sent_for"]
        
        logger.info(f"[{call.from_user.id}] Новое время окончания работы: {new_end.isoformat()}, флаг напоминания сброшен")
        
        text = (
            f"🔄 <b>Работа продлена</b>\n"
            f"• <b>Описание:</b> {work.get('description', 'не указано')}\n"
            f"• <b>Новое время окончания:</b> {new_end.strftime('%d.%m.%Y %H:%M')}"
        )
        async def _send():
            try:
                ok = await send_to_alarm_channels(call.bot, text)
                if not ok:
                    logger.error(f"[{call.from_user.id}] Не удалось отправить сообщение о продлении работы")
                else:
                    logger.info(f"[{call.from_user.id}] Сообщение о продлении работы отправлено в канал")
            except Exception as e:
                logger.warning(f"[{call.from_user.id}] Каналы при продлении работы: %s", e, exc_info=True)
        asyncio.create_task(_send())

        await call.message.edit_text(f"🕒 Работа {work_id} продлена до {new_end.strftime('%d.%m.%Y %H:%M')}", reply_markup=None)
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
        await bot_state.save_state()
        logger.info(f"[{call.from_user.id}] Сохранено состояние после продления работы")
        await state.clear()
        logger.info(f"[{call.from_user.id}] FSM очищена после продления работы")
        await call.answer()
        return
    
    # Продление сбоя (если есть alarm_id)
    if alarm_id:
        alarm = bot_state.active_alarms.get(alarm_id)
        if not alarm:
            logger.warning(f"[{call.from_user.id}] Сбой {alarm_id} не найден при продлении")
            await call.message.edit_text("❌ Сбой не найден", reply_markup=None)
            await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await call.answer()
            return

        logger.info(f"[{call.from_user.id}] Выбрано продление сбоя {alarm_id}: {duration}")

        # Обработка кнопки "Указать вручную" для сбоев
        if duration == "extend_manual":
            logger.info(f"[{call.from_user.id}] Выбран ручной ввод длительности продления сбоя")
            await state.update_data(manual_input_attempts=0)
            await call.message.edit_text(
                "✏️ Введите длительность продления (например: 1 час, 30 минут, 2 часа, 15 минут):",
                reply_markup=create_cancel_keyboard()
            )
            await state.set_state(StopStates.ENTER_ALARM_DURATION_MANUAL)
            await call.answer()
            return
        elif duration == "extend_cancel":
            logger.info(f"[{call.from_user.id}] Продление сбоя отменено")
            await state.clear()
            await call.message.edit_text("🚫 Продление отменено", reply_markup=None)
            await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
            await call.answer()
            return
        
        fix_time_value = alarm.get("fix_time")
        old_end = datetime.fromisoformat(fix_time_value) if isinstance(fix_time_value, str) else fix_time_value
        delta = timedelta(minutes=30) if duration == "extend_30_min" else timedelta(hours=1)
        new_end = old_end + delta
        alarm["fix_time"] = new_end.isoformat()
        # Сбрасываем флаг напоминания при продлении
        if "reminder_sent_for" in alarm:
            del alarm["reminder_sent_for"]
        logger.info(f"[{call.from_user.id}] Новое время окончания: {new_end.isoformat()}, флаг напоминания сброшен")

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

        await call.message.edit_text(f"🕒 Сбой {alarm_id} продлён до {new_end.strftime('%d.%m.%Y %H:%M')}", reply_markup=None)
        await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
        await bot_state.save_state()
        logger.info(f"[{call.from_user.id}] Сохранено состояние после продления")
        await state.clear()
        logger.info(f"[{call.from_user.id}] FSM очищена после продления")
        await call.answer()
        return
    
    # Если нет ни work_id, ни alarm_id
    logger.warning(f"[{call.from_user.id}] Не найдены work_id или alarm_id в состоянии")
    await call.message.edit_text("❌ Ошибка: не найдены данные для продления", reply_markup=None)
    await call.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
    await state.clear()
    await call.answer()
