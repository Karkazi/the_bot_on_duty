"""
Время дежурства: единый часовой пояс для сбоев/работ и напоминаний.

На серверах в UTC naive datetime.now() давал сдвиг относительно машин в Москве.
Переменная BOT_TIMEZONE (по умолчанию Europe/Moscow), переопределяется в .env.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_DEFAULT_TZ = "Europe/Moscow"


def get_bot_timezone_name() -> str:
    return (os.getenv("BOT_TIMEZONE") or _DEFAULT_TZ).strip() or _DEFAULT_TZ


def get_bot_tz() -> ZoneInfo:
    name = get_bot_timezone_name()
    try:
        return ZoneInfo(name)
    except Exception as e:
        logger.warning("Некорректный BOT_TIMEZONE=%r (%s), использую %s", name, e, _DEFAULT_TZ)
        return ZoneInfo(_DEFAULT_TZ)


def bot_now() -> datetime:
    """Текущий момент с привязкой к часовому поясу дежурства (aware)."""
    return datetime.now(get_bot_tz())


def bot_now_naive() -> datetime:
    """
    «Сейчас» как локальные часы в BOT_TIMEZONE без tzinfo — для совместимости
    с уже сохранённым state (ISO без суффикса зоны трактуем как это же локальное время).
    """
    return bot_now().replace(tzinfo=None)
