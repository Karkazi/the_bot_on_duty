"""
Сервис для работы с напоминаниями.
Содержит логику проверки и отправки напоминаний о событиях.
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict

from bot_state import BotState
from utils.datetime_utils import safe_parse_datetime
from domain.constants import REMINDER_MINUTES_BEFORE, JIRA_STATUS_CHECK_INTERVAL, JIRA_STATUS_FIXED_EN, JIRA_STATUS_FIXED_RU
from utils.jira_status_checker import get_jira_issue_status
from config import CONFIG, jira_browse_url
from utils.bot_time import bot_now_naive
from services.max_service import MaxService

logger = logging.getLogger(__name__)
class ReminderService:
    """Сервис для управления напоминаниями"""
    
    def __init__(self, bot_state: BotState):
        """
        Args:
            bot_state: Экземпляр BotState для работы с состоянием
        """
        self.bot_state = bot_state
        self._last_save_time = bot_now_naive()
        self._save_interval = 5  # секунды
    
    async def check_alarm_reminders(self, alarms: Dict[str, Dict]) -> int:
        """
        Проверяет и отправляет напоминания для аварий.
        
        Args:
            bot: Экземпляр бота
            alarms: Словарь аварий
        
        Returns:
            Количество отправленных напоминаний
        """
        count = 0
        now = bot_now_naive()
        
        for alarm_id, alarm in alarms.items():
            try:
                reminder_sent = await self._check_single_alarm_reminder(alarm_id, alarm, now)
                if reminder_sent:
                    count += 1
                    await self._save_if_needed()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка при проверке напоминания для аварии {alarm_id}: {e}", exc_info=True)
        
        return count
    
    async def _check_single_alarm_reminder(
        self,
        alarm_id: str,
        alarm: Dict,
        now: datetime,
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
        
        if reminder_time < now - timedelta(hours=1):
            logger.debug("Время напоминания для %s в прошлом, пропускаем", alarm_id)
            return False
        
        if now >= reminder_time:
            # Проверяем, было ли уже отправлено напоминание
            if self._was_reminder_sent(alarm, fix_time):
                return False
            
            user_id = alarm.get("user_id")
            if not user_id:
                logger.warning(f"Отсутствует user_id для сбоя {alarm_id}")
                return False

            text = f"⚠️ До окончания сбоя {alarm_id} осталось 5 минут.\nПродлевать?"
            reminder_key = fix_time.isoformat() if isinstance(fix_time, datetime) else fix_time

            max_svc = MaxService()
            if not max_svc.is_configured():
                logger.debug("Напоминание по сбою %s: MAX не настроен", alarm_id)
                return False
            try:
                from adapters.max.keyboards import reminder_alarm_attachment_tokens
                ok = await max_svc.send_message_to_user(
                    int(user_id), text, attachment_tokens=reminder_alarm_attachment_tokens()
                )
                if not ok:
                    return False
                self.bot_state.user_states[int(user_id)] = {
                    "type": "reminder",
                    "alarm_id": alarm_id,
                }
                alarm["reminder_sent_for"] = reminder_key
                logger.info(f"Напоминание (MAX) отправлено пользователю {user_id} для аварии {alarm_id}")
                return True
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания MAX для {alarm_id}: {e}", exc_info=True)
                return False
        
        return False
    
    async def check_maintenance_reminders(self, maintenances: Dict[str, Dict]) -> int:
        """
        Проверяет и отправляет напоминания для регламентных работ.
        
        Args:
            bot: Экземпляр бота
            maintenances: Словарь работ
        
        Returns:
            Количество отправленных напоминаний
        """
        count = 0
        now = bot_now_naive()
        
        for work_id, work in maintenances.items():
            try:
                reminder_sent = await self._check_single_maintenance_reminder(work_id, work, now)
                if reminder_sent:
                    count += 1
                    await self._save_if_needed()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка при проверке напоминания для работы {work_id}: {e}", exc_info=True)
        
        return count
    
    async def _check_single_maintenance_reminder(
        self,
        work_id: str,
        work: Dict,
        now: datetime,
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
        
        # Просроченное напоминание — не спамим в лог; работа должна быть убрана cleanup при старте
        if reminder_time < now - timedelta(hours=1):
            if isinstance(end_time, datetime) and end_time <= now:
                logger.debug("Работа %s уже завершена, напоминание не требуется", work_id)
            else:
                logger.debug("Время напоминания для работы %s в прошлом, пропускаем", work_id)
            return False
        
        if now >= reminder_time:
            # Проверяем, было ли уже отправлено напоминание
            if self._was_reminder_sent(work, end_time):
                return False
            
            user_id = work.get("user_id")
            if not user_id:
                logger.warning(f"Отсутствует user_id для работы {work_id}")
                return False

            text = f"⚠️ До окончания работы {work_id} осталось 5 минут.\nПродлевать или завершить?"
            reminder_key = end_time.isoformat() if isinstance(end_time, datetime) else end_time

            max_svc = MaxService()
            if not max_svc.is_configured():
                logger.debug("Напоминание по работе %s: MAX не настроен", work_id)
                return False
            try:
                from adapters.max.keyboards import reminder_maintenance_attachment_tokens
                ok = await max_svc.send_message_to_user(
                    int(user_id), text, attachment_tokens=reminder_maintenance_attachment_tokens()
                )
                if not ok:
                    return False
                self.bot_state.user_states[int(user_id)] = {
                    "type": "maintenance_reminder",
                    "work_id": work_id,
                }
                work["reminder_sent_for"] = reminder_key
                logger.info(f"Напоминание (MAX) отправлено пользователю {user_id} для работы {work_id}")
                return True
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания MAX для работы {work_id}: {e}", exc_info=True)
                return False
        
        return False
    
    async def check_jira_statuses(self, alarms: Dict[str, Dict]) -> int:
        """
        Проверяет статусы задач в Jira и автоматически закрывает аварии.
        
        Args:
            bot: Экземпляр бота
            alarms: Словарь аварий
        
        Returns:
            Количество автоматически закрытых аварий
        """
        count = 0
        now = bot_now_naive()
        
        for alarm_id, alarm in alarms.items():
            try:
                closed = await self._check_single_jira_status(alarm_id, alarm, now)
                if closed:
                    count += 1
                    await self._save_if_needed()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка при проверке статуса Jira для {alarm_id}: {e}", exc_info=True)
        
        return count
    
    async def _check_single_jira_status(
        self,
        alarm_id: str,
        alarm: Dict,
        now: datetime,
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
                alarm_service = AlarmService(self.bot_state)
                closed_alarm = alarm_service.close_alarm(alarm_id)

                import asyncio
                from datetime import datetime as _dt

                async def _task_petlocal():
                    if not closed_alarm.get("publish_petlocal", True):
                        return
                    try:
                        from services.simpleone_service import SimpleOneService
                        closed_at = bot_now_naive().strftime("%d.%m.%Y %H:%M")
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
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning(f"Ошибка при публикации на Петлокале для {alarm_id}: {e}")

                async def _task_channels():
                    try:
                        from utils.channel_helpers import send_to_alarm_channel
                        text = f"✅ Сбой устранён\n• Проблема: {closed_alarm.get('issue', 'не указано')}"
                        await send_to_alarm_channel(text)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning(f"Каналы при закрытии {alarm_id}: {e}", exc_info=True)

                async def _task_jira_time_end():
                    try:
                        from utils.jira_close_fa import resolve_jira_key, set_time_end_problem

                        jk = resolve_jira_key(alarm_id, closed_alarm)
                        if not jk:
                            return
                        ok = await set_time_end_problem(jk, now)
                        if not ok:
                            logger.warning(
                                "[AUTO_CLOSE] Не удалось проставить TimeEndProblem для %s",
                                jk,
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning(
                            "[AUTO_CLOSE] JIRA TimeEndProblem для %s: %s",
                            alarm_id,
                            e,
                            exc_info=True,
                        )

                async def _task_max_archive():
                    """Как при ручном stop_alarm: заголовок чата, экспорт в JIRA, очистка чата."""
                    try:
                        from services.max_archive import process_max_chat_on_alarm_close

                        max_chat_id = closed_alarm.get("max_chat_id")
                        if max_chat_id is not None:
                            max_chat_id = str(max_chat_id).strip() or None
                        if not max_chat_id:
                            chat_ids = (CONFIG.get("MAX") or {}).get("ALARM_FA_CHAT_IDS") or []
                            if chat_ids:
                                max_chat_id = str(chat_ids[0]).strip() or None
                            if max_chat_id:
                                logger.info(
                                    "Автозакрытие %s: нет max_chat_id — используем первый ALARM_FA_CHAT_IDS",
                                    alarm_id,
                                )
                        if not max_chat_id:
                            return
                        max_svc = MaxService()
                        if not max_svc.is_configured():
                            return
                        await max_svc.set_chat_title(max_chat_id, f"✅ {alarm_id}"[:200])
                        jk = (closed_alarm.get("jira_key") or jira_key or "").strip() or None
                        ok = await process_max_chat_on_alarm_close(alarm_id, max_chat_id, jira_key=jk)
                        if jk and not ok:
                            logger.warning(
                                "[AUTO_CLOSE] Архив MAX→JIRA для %s не завершён (чат может быть не очищен)",
                                alarm_id,
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning(
                            "[AUTO_CLOSE] Ошибка архивации чата MAX для %s: %s",
                            alarm_id,
                            e,
                            exc_info=True,
                        )

                await asyncio.gather(
                    _task_petlocal(),
                    _task_channels(),
                    _task_max_archive(),
                    _task_jira_time_end(),
                )

                user_id = closed_alarm.get("user_id")
                if user_id:
                    try:
                        max_svc = MaxService()
                        if max_svc.is_configured():
                            jira_url = jira_browse_url(jira_key)
                            msg = (
                                f"✅ Сбой {alarm_id} устранен.\n"
                                f"Задача в Jira {jira_key} переведена в статус \"{JIRA_STATUS_FIXED_RU}\"."
                            )
                            if jira_url:
                                msg += f"\n🔗 {jira_url}"
                            await max_svc.send_message_to_user(int(user_id), msg, strip_html=True)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning(f"Не удалось уведомить пользователя {user_id} в MAX: {e}")
                
                logger.info(f"Авария {alarm_id} (Jira: {jira_key}) автоматически закрыта по статусу")
                return True
            else:
                # Сохраняем время последней проверки
                alarm["last_status_check"] = now.isoformat()
                return False
        
        except asyncio.CancelledError:
            raise
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
        now = bot_now_naive()
        if (now - self._last_save_time).total_seconds() >= self._save_interval:
            try:
                await self.bot_state.save_state()
                self._last_save_time = now
                logger.debug("Состояние сохранено после обновления напоминаний")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка сохранения состояния: {e}", exc_info=True)

