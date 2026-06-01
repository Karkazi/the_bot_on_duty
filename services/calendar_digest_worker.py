"""Фоновый планировщик ежедневной сводки календаря."""

from services.calendar_digest_service import run_calendar_digest_scheduler

__all__ = ["run_calendar_digest_scheduler"]
