"""
Утилиты для работы с датой и временем.
Централизованные функции для парсинга и форматирования.
Поддержка гибкого ввода: «02.02.2026 14:00», «через 1 час», «завтра 10:00», «сегодня 14:00».
"""
from datetime import datetime, timedelta
from typing import Optional, Union
import re
import logging

from domain.constants import DATETIME_FORMAT

logger = logging.getLogger(__name__)


def safe_parse_datetime(
    time_value: Union[str, datetime],
    format_str: Optional[str] = None
) -> Optional[datetime]:
    """
    Безопасный парсер даты и времени.
    Поддерживает ISO формат и кастомный формат.
    
    Args:
        time_value: Значение времени (строка или datetime)
        format_str: Формат для парсинга (если None, используется ISO)
    
    Returns:
        datetime объект или None если не удалось распарсить
    """
    if not time_value:
        return None
    
    # Если уже datetime, возвращаем как есть
    if isinstance(time_value, datetime):
        return time_value
    
    # Пробуем ISO формат
    if isinstance(time_value, str):
        try:
            return datetime.fromisoformat(time_value)
        except (ValueError, TypeError):
            pass
        
        # Пробуем кастомный формат
        if format_str:
            try:
                return datetime.strptime(time_value, format_str)
            except (ValueError, TypeError):
                pass
    
    logger.warning(f"Не удалось распарсить время: {time_value}")
    return None


def format_datetime(dt: Union[datetime, str], format_str: str = DATETIME_FORMAT) -> str:
    """
    Форматирует datetime в строку.
    
    Args:
        dt: datetime объект или ISO строка
        format_str: Формат для форматирования
    
    Returns:
        Отформатированная строка
    """
    if isinstance(dt, str):
        dt = safe_parse_datetime(dt)
        if not dt:
            return dt  # Возвращаем исходную строку если не удалось распарсить
    
    if isinstance(dt, datetime):
        return dt.strftime(format_str)
    
    return str(dt)


def parse_flexible_datetime(
    text: str,
    base_time: Optional[datetime] = None,
    format_str: str = DATETIME_FORMAT,
) -> Optional[datetime]:
    """
    Парсит дату/время из строки в разных форматах (как в Telegram: ручной ввод и удобные варианты).

    Поддерживаются:
    - Строгий формат: «дд.мм.гггг чч:мм» (например 02.02.2026 14:00).
    - Относительно base_time (по умолчанию now): «через 30 мин», «через 1 час», «через 2 часа».
    - Дата словом: «сегодня 14:00», «завтра 10:00».
    - Только время: «14:00» — сегодня (или base_time.date()) в это время.

    Returns:
        datetime или None, если не удалось разобрать.
    """
    if not text or not text.strip():
        return None
    text = text.strip().lower()
    base = base_time or datetime.now()

    # 1) Строгий формат дд.мм.гггг чч:мм
    try:
        return datetime.strptime(text, format_str)
    except ValueError:
        pass

    # 2) «через N мин/час/дней» относительно base
    if text.startswith("через "):
        from utils.helpers import parse_duration
        delta = parse_duration(text)
        if delta is not None:
            return base + delta
    # без «через»: «1 час», «30 мин»
    from utils.helpers import parse_duration
    delta = parse_duration(text)
    if delta is not None:
        return base + delta

    # 3) «сегодня 14:00» / «завтра 10:00»
    today = base.replace(hour=0, minute=0, second=0, microsecond=0)
    for label, day_delta in (("сегодня", 0), ("завтра", 1), ("послезавтра", 2)):
        if text.startswith(label + " ") or text == label:
            rest = text[len(label):].strip()
            if not rest:
                return today + timedelta(days=day_delta)
            # парсим время чч:мм или чч:мм:сс
            time_match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", rest)
            if time_match:
                h, m = int(time_match.group(1)), int(time_match.group(2))
                if 0 <= h <= 23 and 0 <= m <= 59:
                    d = today + timedelta(days=day_delta)
                    return d.replace(hour=h, minute=m, second=0, microsecond=0)
            break

    # 4) Только время «14:00» — сегодня (или дата base) в это время
    time_only = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", text)
    if time_only:
        h, m = int(time_only.group(1)), int(time_only.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return base.replace(hour=h, minute=m, second=0, microsecond=0)

    return None


def parse_duration_to_timedelta(duration_str: str) -> Optional[timedelta]:
    """
    Парсит строку с длительностью в timedelta.
    Альтернативное имя для parse_duration из helpers для единообразия.
    
    Args:
        duration_str: Строка вида "1 час", "30 минут", "2 дня"
    
    Returns:
        timedelta объект или None
    """
    from utils.helpers import parse_duration
    return parse_duration(duration_str)

