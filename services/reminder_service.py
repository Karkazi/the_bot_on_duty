"""
Сервис для работы с напоминаниями.
Содержит логику проверки и отправки напоминаний о событиях.
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional

from aiogram import Bot
from bot_state import BotState
from utils.exceptions import BotError
from utils.datetime_utils import safe_parse_datetime
from domain.constants import REMINDER_MINUTES_BEFORE, JIRA_STATUS_CHECK_INTERVAL, JIRA_STATUS_FIXED_EN, JIRA_STATUS_FIXED_RU
from utils.jira_status_checker import get_jira_issue_status
from keyboards import create_reminder_keyboard, create_maintenance_reminder_keyboard
from config import jira_browse_url

logger = logging.getLogger(__name__)


class ReminderService:
    """Сервис для управления напоминаниями"""
    
    def __init__(self, bot_state: BotState):
        """
        Args:
            bot_state: Экземпляр BotState для работы с состоянием
        """
        self.bot_state = bot_state
        self._last_save_time = datetime.now()
        self._save_interval = 5  # секунды
    
    async def check_alarm_reminders(self, bot: Bot, alarms: Dict[str, Dict]) -> int:
        """
        Проверяет и отправляет напоминания для аварий.
        
        Args:
            bot: Экземпляр бота
            alarms: Словарь аварий
        
        Returns:
            Количество отправленных напоминаний
        """
        count = 0
        now = datetime.now()
        
        for alarm_id, alarm in alarms.items():
            try:
                reminder_sent = await self._check_single_alarm_reminder(bot, alarm_id, alarm, now)
                if reminder_sent:
                    count += 1
                    await self._save_if_needed()
            except Exception as e:
                logger.error(f"Ошибка при проверке напоминания для аварии {alarm_id}: {e}", exc_info=True)
        
        return count
    
    async def _check_single_alarm_reminder(
        self,
        bot: Bot,
        alarm_id: str,
        alarm: Dict,
        now: datetime
    ) -> bool:
        """Проверяет и отправляет напоминание для одной аварии"""
        fix_time_value = alarm.get("fix_time")
        if not fix_time_value:
            return False
        
        # Парсим время
        fix_time = safe_parse_datetime(fix_time_value)
        if not fix_time:
            logger.warning(f"Некорректный тип fix_time для сбоя {alarm_id}")
            return False
        
        reminder_time = fix_time - timedelta(minutes=REMINDER_MINUTES_BEFORE)
        
        # Проверяем, что reminder_time не в прошлом
        if reminder_time < now - timedelta(hours=1):
            logger.warning(f"Время напоминания для {alarm_id} слишком в прошлом, пропускаем")
            return False
        
        if now >= reminder_time:
            # Проверяем, было ли уже отправлено напоминание
            if self._was_reminder_sent(alarm, fix_time):
                return False
            
            # Отправляем напоминание
            user_id = alarm.get("user_id")
            if not user_id:
                logger.warning(f"Отсутствует user_id для сбоя {alarm_id}")
                return False
            
            try:
                msg = await bot.send_message(
                    user_id,
                    f"⚠️ До окончания сбоя {alarm_id} осталось 5 минут.\nПродлевать?",
                    reply_markup=create_reminder_keyboard()
                )
                self.bot_state.user_states[user_id] = {
                    "type": "reminder",
                    "alarm_id": alarm_id,
                    "chat_id": msg.chat.id,
                    "message_id": msg.message_id
                }
                # Сохраняем время, для которого отправили напоминание
                alarm["reminder_sent_for"] = fix_time.isoformat() if isinstance(fix_time, datetime) else fix_time
                logger.info(f"Напоминание отправлено пользователю {user_id} для аварии {alarm_id}")
                return True
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания для {alarm_id}: {e}", exc_info=True)
                return False
        
        return False
    
    async def check_maintenance_reminders(self, bot: Bot, maintenances: Dict[str, Dict]) -> int:
        """
        Проверяет и отправляет напоминания для регламентных работ.
        
        Args:
            bot: Экземпляр бота
            maintenances: Словарь работ
        
        Returns:
            Количество отправленных напоминаний
        """
        count = 0
        now = datetime.now()
        
        for work_id, work in maintenances.items():
            try:
                reminder_sent = await self._check_single_maintenance_reminder(bot, work_id, work, now)
                if reminder_sent:
                    count += 1
                    await self._save_if_needed()
            except Exception as e:
                logger.error(f"Ошибка при проверке напоминания для работы {work_id}: {e}", exc_info=True)
        
        return count
    
    async def _check_single_maintenance_reminder(
        self,
        bot: Bot,
        work_id: str,
        work: Dict,
        now: datetime
    ) -> bool:
        """Проверяет и отправляет напоминание для одной работы"""
        end_time_value = work.get("end_time") or work.get("end")
        if not end_time_value:
            return False
        
        # Парсим время
        end_time = safe_parse_datetime(end_time_value)
        if not end_time:
            logger.warning(f"Некорректный тип end_time для работы {work_id}")
            return False
        
        reminder_time = end_time - timedelta(minutes=REMINDER_MINUTES_BEFORE)
        
        # Проверяем, что reminder_time не в прошлом
        if reminder_time < now - timedelta(hours=1):
            logger.warning(f"Время напоминания для работы {work_id} слишком в прошлом, пропускаем")
            return False
        
        if now >= reminder_time:
            # Проверяем, было ли уже отправлено напоминание
            if self._was_reminder_sent(work, end_time):
                return False
            
            # Отправляем напоминание
            user_id = work.get("user_id")
            if not user_id:
                logger.warning(f"Отсутствует user_id для работы {work_id}")
                return False
            
            try:
                msg = await bot.send_message(
                    user_id,
                    f"⚠️ До окончания работы {work_id} осталось 5 минут.\nПродлевать или завершить?",
                    reply_markup=create_maintenance_reminder_keyboard()
                )
                self.bot_state.user_states[user_id] = {
                    "type": "maintenance_reminder",
                    "work_id": work_id,
                    "chat_id": msg.chat.id,
                    "message_id": msg.message_id
                }
                # Сохраняем время, для которого отправили напоминание
                work["reminder_sent_for"] = end_time.isoformat() if isinstance(end_time, datetime) else end_time
                logger.info(f"Напоминание отправлено пользователю {user_id} для работы {work_id}")
                return True
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания для работы {work_id}: {e}", exc_info=True)
                return False
        
        return False
    
    async def check_jira_statuses(self, bot: Bot, alarms: Dict[str, Dict]) -> int:
        """
        Проверяет статусы задач в Jira и автоматически закрывает аварии.
        
        Args:
            bot: Экземпляр бота
            alarms: Словарь аварий
        
        Returns:
            Количество автоматически закрытых аварий
        """
        count = 0
        now = datetime.now()
        
        for alarm_id, alarm in alarms.items():
            try:
                closed = await self._check_single_jira_status(bot, alarm_id, alarm, now)
                if closed:
                    count += 1
                    await self._save_if_needed()
            except Exception as e:
                logger.error(f"Ошибка при проверке статуса Jira для {alarm_id}: {e}", exc_info=True)
        
        return count
    
    async def _check_single_jira_status(
        self,
        bot: Bot,
        alarm_id: str,
        alarm: Dict,
        now: datetime
    ) -> bool:
        """Проверяет статус одной задачи в Jira"""
        jira_key = alarm.get("jira_key")
        if not jira_key:
            return False
        
        # Проверяем, не проверяли ли недавно
        last_check = alarm.get("last_status_check")
        if last_check:
            try:
                last_check_dt = safe_parse_datetime(last_check)
                
                if last_check_dt:
                    time_since_check = (now - last_check_dt).total_seconds()
                    if time_since_check < JIRA_STATUS_CHECK_INTERVAL:
                        return False  # Пропускаем, если недавно проверяли
            except (ValueError, TypeError) as e:
                logger.warning(f"Ошибка парсинга last_status_check для {alarm_id}: {e}")
        
        try:
            # Получаем статус задачи из Jira
            status = await get_jira_issue_status(jira_key)
            
            if status is None:
                logger.warning(f"Не удалось получить статус для {jira_key}")
                return False
            
            # Проверяем статус
            status_normalized = status.strip().lower()
            expected_status_en = JIRA_STATUS_FIXED_EN.strip().lower()
            expected_status_ru = JIRA_STATUS_FIXED_RU.strip().lower()
            
            is_fixed = (
                status == JIRA_STATUS_FIXED_EN or
                status == JIRA_STATUS_FIXED_RU or
                status_normalized == expected_status_en or
                status_normalized == expected_status_ru
            )
            
            if is_fixed:
                # Автоматически закрываем аварию
                # Импорты внутри функции для избежания циклических зависимостей
                from services.alarm_service import AlarmService
                from utils.channel_helpers import send_to_alarm_channels

                alarm_service = AlarmService(self.bot_state)
                closed_alarm = alarm_service.close_alarm(alarm_id)

                if closed_alarm.get("publish_petlocal", True):
                    try:
                        from datetime import datetime as _dt
                        from services.simpleone_service import SimpleOneService

                        closed_at = _dt.now().strftime("%d.%m.%Y %H:%M")
                        async with SimpleOneService() as simpleone:
                            html = simpleone.format_alarm_closed_for_petlocal(
                                alarm_id=alarm_id,
                                issue=closed_alarm.get("issue", "не указано"),
                                closed_at=closed_at
                            )
                            result = await simpleone.create_portal_post(html)
                            if result.get("success"):
                                logger.info(f"Пост о закрытии сбоя {alarm_id} опубликован на Петлокале")
                            else:
                                logger.warning(f"Не удалось опубликовать пост на Петлокале для {alarm_id}: {result.get('error', '')}")
                    except Exception as e:
                        logger.warning(f"Ошибка при публикации на Петлокале для {alarm_id}: {e}")

                # Обрабатываем закрытие в SCM (импорт внутри для избежания циклических зависимостей)
                try:
                    from handlers.manage.scm import handle_scm_alarm_close
                    await handle_scm_alarm_close(bot, alarm_id, closed_alarm)
                except ImportError:
                    logger.warning("Не удалось импортировать handle_scm_alarm_close")

                # Отправляем сообщение в канал (Telegram и при наличии настроек — MAX)
                text = f"✅ Сбой устранён\n• Проблема: {closed_alarm.get('issue', 'не указано')}"
                await send_to_alarm_channels(bot, text, parse_mode=None)
                
                # Уведомляем пользователя
                user_id = closed_alarm.get("user_id")
                if user_id:
                    try:
                        jira_url = jira_browse_url(jira_key)
                        await bot.send_message(
                            user_id,
                            f"✅ Сбой {alarm_id} устранен.\n"
                            f"Задача в Jira {jira_key} переведена в статус \"{JIRA_STATUS_FIXED_RU}\".\n"
                            f"🔗 <a href='{jira_url}'>Открыть задачу</a>",
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось уведомить пользователя {user_id}: {e}")
                
                logger.info(f"Авария {alarm_id} (Jira: {jira_key}) автоматически закрыта по статусу")
                return True
            else:
                # Сохраняем время последней проверки
                alarm["last_status_check"] = now.isoformat()
                return False
        
        except Exception as e:
            logger.error(f"Ошибка проверки статуса {jira_key}: {e}", exc_info=True)
            return False
    
    def _was_reminder_sent(self, item: Dict, target_time: datetime) -> bool:
        """Проверяет, было ли уже отправлено напоминание для указанного времени"""
        last_reminder_time = item.get("reminder_sent_for")
        if not last_reminder_time:
            return False
        
        try:
            last_reminder_dt = safe_parse_datetime(last_reminder_time)
            if not last_reminder_dt:
                return False
            
            return last_reminder_dt == target_time
        except (ValueError, TypeError):
            return False
    
    async def _save_if_needed(self) -> None:
        """Сохраняет состояние, если прошло достаточно времени"""
        now = datetime.now()
        if (now - self._last_save_time).total_seconds() >= self._save_interval:
            try:
                await self.bot_state.save_state()
                self._last_save_time = now
                logger.debug("Состояние сохранено после обновления напоминаний")
            except Exception as e:
                logger.error(f"Ошибка сохранения состояния: {e}", exc_info=True)

