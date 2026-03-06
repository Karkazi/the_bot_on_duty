"""
Сервис для работы с регламентными работами (maintenances).
Содержит бизнес-логику создания, управления и закрытия работ.
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional

from bot_state import BotState
from utils.exceptions import NotFoundError, ValidationError
from utils.datetime_utils import safe_parse_datetime
from domain.constants import DATETIME_FORMAT

logger = logging.getLogger(__name__)


class MaintenanceService:
    """Сервис для управления регламентными работами"""
    
    def __init__(self, bot_state: BotState):
        """
        Args:
            bot_state: Экземпляр BotState для работы с состоянием
        """
        self.bot_state = bot_state
    
    def create_maintenance(
        self,
        description: str,
        start_time: datetime,
        end_time: datetime,
        user_id: int,
        unavailable_services: str = "не указано"
    ) -> str:
        """
        Создает новую регламентную работу.
        
        Args:
            description: Описание работ
            start_time: Время начала
            end_time: Время окончания
            user_id: ID пользователя
            unavailable_services: Недоступные сервисы
        
        Returns:
            ID созданной работы
        
        Raises:
            ValidationError: Если данные некорректны
        """
        # Валидация
        if not description or not description.strip():
            raise ValidationError("Описание работ не может быть пустым", "description")
        
        if start_time < datetime.now():
            raise ValidationError("Время начала не может быть в прошлом", "start_time")
        
        if end_time <= start_time:
            raise ValidationError("Время окончания должно быть позже начала", "end_time")
        
        # Генерируем ID
        work_id = str(uuid.uuid4())[:4]
        
        # Создаем работу
        self.bot_state.active_maintenances[work_id] = {
            "description": description,
            "start_time": start_time.isoformat() if isinstance(start_time, datetime) else start_time,
            "end_time": end_time.isoformat() if isinstance(end_time, datetime) else end_time,
            "unavailable_services": unavailable_services,
            "user_id": user_id,
            "created_at": datetime.now().isoformat()
        }
        
        logger.info(f"Создана работа {work_id} пользователем {user_id}")
        return work_id
    
    def get_maintenance(self, work_id: str) -> Dict:
        """
        Получает работу по ID.
        
        Args:
            work_id: ID работы
        
        Returns:
            Данные работы
        
        Raises:
            NotFoundError: Если работа не найдена
        """
        if work_id not in self.bot_state.active_maintenances:
            raise NotFoundError(f"Работа {work_id} не найдена")
        
        return self.bot_state.active_maintenances[work_id]
    
    def extend_maintenance(
        self,
        work_id: str,
        new_end_time: datetime
    ) -> datetime:
        """
        Продлевает работу до нового времени окончания.
        
        Args:
            work_id: ID работы
            new_end_time: Новое время окончания
        
        Returns:
            Новое время окончания
        
        Raises:
            NotFoundError: Если работа не найдена
            ValidationError: Если новое время некорректно
        """
        work = self.get_maintenance(work_id)
        
        # Парсим текущее время окончания
        end_time_value = work.get("end_time")
        if isinstance(end_time_value, str):
            current_end_time = datetime.fromisoformat(end_time_value)
        elif isinstance(end_time_value, datetime):
            current_end_time = end_time_value
        else:
            raise ValidationError("Некорректное время окончания", "end_time")
        
        # Валидация
        if new_end_time <= current_end_time:
            raise ValidationError(
                f"Новое время окончания должно быть позже текущего ({current_end_time.strftime(DATETIME_FORMAT)})",
                "end_time"
            )
        
        # Обновляем
        work["end_time"] = new_end_time.isoformat()
        
        # Сбрасываем флаг напоминания
        if "reminder_sent_for" in work:
            del work["reminder_sent_for"]
        
        logger.info(f"Работа {work_id} продлена до {new_end_time.isoformat()}")
        return new_end_time
    
    def extend_maintenance_by_duration(
        self,
        work_id: str,
        duration: timedelta
    ) -> datetime:
        """
        Продлевает работу на указанное время.
        
        Args:
            work_id: ID работы
            duration: Длительность продления
        
        Returns:
            Новое время окончания
        """
        work = self.get_maintenance(work_id)
        
        # Парсим текущее время окончания
        end_time_value = work.get("end_time")
        current_end_time = safe_parse_datetime(end_time_value)
        if not current_end_time:
            raise ValidationError("Некорректное время окончания", "end_time")
        
        new_end_time = current_end_time + duration
        return self.extend_maintenance(work_id, new_end_time)
    
    def close_maintenance(self, work_id: str) -> Dict:
        """
        Закрывает работу.
        
        Args:
            work_id: ID работы
        
        Returns:
            Данные закрытой работы
        
        Raises:
            NotFoundError: Если работа не найдена
        """
        work = self.get_maintenance(work_id)
        
        # Удаляем из активных
        del self.bot_state.active_maintenances[work_id]
        
        logger.info(f"Работа {work_id} закрыта")
        return work
    
    def get_user_maintenances(self, user_id: int, include_superadmin: bool = False) -> Dict[str, Dict]:
        """
        Получает все активные работы пользователя.
        
        Args:
            user_id: ID пользователя
            include_superadmin: Включить работы суперадминов
        
        Returns:
            Словарь {work_id: work_data}
        """
        return self.bot_state.get_user_active_maintenances(user_id)
    
    def update_maintenance_field(self, work_id: str, field: str, value: any) -> None:
        """
        Обновляет поле работы.
        
        Args:
            work_id: ID работы
            field: Название поля
            value: Новое значение
        
        Raises:
            NotFoundError: Если работа не найдена
        """
        work = self.get_maintenance(work_id)
        work[field] = value
        logger.debug(f"Обновлено поле {field} для работы {work_id}")

