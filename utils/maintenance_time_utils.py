"""
Утилиты для работы с временем регламентных работ
"""
from datetime import datetime as dt, timedelta
from typing import Tuple, Optional
from domain.constants import MAINTENANCE_TIME_SPINNER_CONFIG, MAINTENANCE_TIME_STEPS_ORDER
import logging

logger = logging.getLogger(__name__)


class MaintenanceTimeSpinner:
    """Управление спиннерами для выбора времени работ"""
    
    @staticmethod
    def increment_value(
        field_type: str,
        current_value: int,
        step: int = 1
    ) -> int:
        """
        Увеличить значение с циклическим переходом
        
        Args:
            field_type: Тип поля (hour_start, minute_start, hour_end, minute_end, date)
            current_value: Текущее значение
            step: Шаг увеличения
        
        Returns:
            Новое значение
        
        Примеры:
            hour_start 23 + 1 = 0 (циклический переход)
            minute_start 45 + 15 = 0 (циклический переход)
        """
        config = MAINTENANCE_TIME_SPINNER_CONFIG.get(field_type)
        if not config:
            return current_value
        
        max_val = config["max"]
        min_val = config["min"]
        actual_step = config.get("step", step)
        
        new_value = current_value + actual_step
        
        # Циклический переход
        if new_value > max_val:
            new_value = min_val
        
        return new_value
    
    @staticmethod
    def decrement_value(
        field_type: str,
        current_value: int,
        step: int = 1
    ) -> int:
        """
        Уменьшить значение с циклическим переходом
        
        Примеры:
            hour_start 0 - 1 = 23 (циклический переход)
            minute_start 0 - 15 = 45 (циклический переход)
        """
        config = MAINTENANCE_TIME_SPINNER_CONFIG.get(field_type)
        if not config:
            return current_value
        
        max_val = config["max"]
        min_val = config["min"]
        actual_step = config.get("step", step)
        
        new_value = current_value - actual_step
        
        # Циклический переход
        if new_value < min_val:
            new_value = max_val
        
        return new_value
    
    @staticmethod
    def get_next_step(current_step_index: int) -> Optional[str]:
        """Получить следующий шаг в процессе"""
        if current_step_index < len(MAINTENANCE_TIME_STEPS_ORDER) - 1:
            return MAINTENANCE_TIME_STEPS_ORDER[current_step_index + 1]
        return None
    
    @staticmethod
    def get_prev_step(current_step_index: int) -> Optional[str]:
        """Получить предыдущий шаг в процессе"""
        if current_step_index > 0:
            return MAINTENANCE_TIME_STEPS_ORDER[current_step_index - 1]
        return None
    
    @staticmethod
    def get_step_index(field_type: str) -> int:
        """Получить индекс шага по типу поля"""
        try:
            return MAINTENANCE_TIME_STEPS_ORDER.index(field_type)
        except ValueError:
            return 0
    
    @staticmethod
    def validate_time_range(
        hour_start: int,
        minute_start: int,
        hour_end: int,
        minute_end: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Валидировать что время окончания > время начала
        
        Returns:
            (is_valid, error_message)
        """
        # Преобразуем в минуты от начала дня
        start_minutes = hour_start * 60 + minute_start
        end_minutes = hour_end * 60 + minute_end
        
        if end_minutes <= start_minutes:
            return False, (
                f"⚠️ Время окончания должно быть позже начала\n"
                f"Начало: {hour_start:02d}:{minute_start:02d}\n"
                f"Конец: {hour_end:02d}:{minute_end:02d}"
            )
        
        return True, None
    
    @staticmethod
    def build_datetime(
        days_offset: int,
        hour: int,
        minute: int
    ) -> dt:
        """
        Построить datetime объект
        
        Args:
            days_offset: Смещение дней от сегодня
            hour: Часы
            minute: Минуты
        
        Returns:
            datetime объект
        """
        now = dt.now()
        target_date = now + timedelta(days=days_offset)
        return target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    @staticmethod
    def format_time_display(
        date_offset: int,
        hour_start: int,
        minute_start: int,
        date_end_offset: int,
        hour_end: int,
        minute_end: int
    ) -> str:
        """
        Форматировать время для отображения
        
        Пример:
            📅 20 декабря
            ⏰ 10:00 - 12:00
        или если даты разные:
            📅 20 декабря 10:00 - 21 декабря 12:00
        """
        months = [
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ]
        
        start_date = dt.now() + timedelta(days=date_offset)
        end_date = dt.now() + timedelta(days=date_end_offset)
        
        time_start = f"{hour_start:02d}:{minute_start:02d}"
        time_end = f"{hour_end:02d}:{minute_end:02d}"
        
        # Если даты одинаковые, показываем одну дату
        if date_offset == date_end_offset:
            date_str = f"{start_date.day} {months[start_date.month - 1]}"
            return f"📅 {date_str}\n⏰ {time_start} - {time_end}"
        else:
            # Если даты разные, показываем обе
            start_date_str = f"{start_date.day} {months[start_date.month - 1]}"
            end_date_str = f"{end_date.day} {months[end_date.month - 1]}"
            return f"📅 {start_date_str} {time_start} - {end_date_str} {time_end}"

