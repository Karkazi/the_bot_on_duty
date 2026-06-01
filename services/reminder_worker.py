"""Фоновая проверка напоминаний (MAX)."""
import asyncio
import logging

from bot_state import bot_state
from utils.bot_time import bot_now_naive

logger = logging.getLogger(__name__)


async def check_reminders() -> None:
    from services.reminder_service import ReminderService

    reminder_service = ReminderService(bot_state)
    while True:
        try:
            now = bot_now_naive()
            logger.debug("[REMINDER] Проверка уведомлений. Текущее время: %s", now.isoformat())
            alarms_snapshot = dict(bot_state.active_alarms)
            maintenances_snapshot = dict(bot_state.active_maintenances)
            alarm_reminders = await reminder_service.check_alarm_reminders(alarms_snapshot)
            maintenance_reminders = await reminder_service.check_maintenance_reminders(maintenances_snapshot)
            closed_by_jira = await reminder_service.check_jira_statuses(alarms_snapshot)
            if alarm_reminders > 0 or maintenance_reminders > 0 or closed_by_jira > 0:
                logger.info(
                    "[REMINDER] аварии=%s, работы=%s, закрыто по Jira=%s",
                    alarm_reminders, maintenance_reminders, closed_by_jira,
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.critical("[REMINDER] Критическая ошибка: %s", e, exc_info=True)
        await asyncio.sleep(60)
