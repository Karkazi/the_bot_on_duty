"""
Сервис для работы с авариями (alarms).
Содержит бизнес-логику создания, управления и закрытия аварий.
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


class AlarmService:
    """Сервис для управления авариями"""
    
    def __init__(self, bot_state: BotState):
        """
        Args:
            bot_state: Экземпляр BotState для работы с состоянием
        """
        self.bot_state = bot_state
    
    def create_alarm(
        self,
        issue: str,
        fix_time: datetime,
        user_id: int,
        service: str,
        jira_key: Optional[str] = None,
        has_jira: bool = False,
        scm_topic_id: Optional[int] = None
    ) -> str:
        """
        Создает новую аварию.
        
        Args:
            issue: Описание проблемы
            fix_time: Время исправления
            user_id: ID пользователя
            service: Затронутый сервис
            jira_key: Ключ задачи в Jira (если есть)
            has_jira: Есть ли задача в Jira
            scm_topic_id: ID темы в SCM канале (если есть)
        
        Returns:
            ID созданной аварии
        
        Raises:
            ValidationError: Если данные некорректны
        """
        # Валидация
        if not issue or not issue.strip():
            raise ValidationError("Описание проблемы не может быть пустым", "issue")
        
        if fix_time < datetime.now():
            raise ValidationError("Время исправления не может быть в прошлом", "fix_time")
        
        if not service:
            raise ValidationError("Сервис не указан", "service")
        
        # Генерируем ID
        if jira_key:
            alarm_id = jira_key
        else:
            alarm_id = str(uuid.uuid4())[:8]
        
        # Создаем аварию
        self.bot_state.active_alarms[alarm_id] = {
            "issue": issue,
            "fix_time": fix_time.isoformat() if isinstance(fix_time, datetime) else fix_time,
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "jira_key": jira_key,
            "has_jira": has_jira,
            "scm_topic_id": scm_topic_id
        }
        
        logger.info(f"Создана авария {alarm_id} пользователем {user_id}")
        return alarm_id
    
    def get_alarm(self, alarm_id: str) -> Dict:
        """
        Получает аварию по ID.
        
        Args:
            alarm_id: ID аварии
        
        Returns:
            Данные аварии
        
        Raises:
            NotFoundError: Если авария не найдена
        """
        if alarm_id not in self.bot_state.active_alarms:
            raise NotFoundError(f"Авария {alarm_id} не найдена")
        
        return self.bot_state.active_alarms[alarm_id]
    
    def extend_alarm(
        self,
        alarm_id: str,
        duration: timedelta
    ) -> datetime:
        """
        Продлевает аварию на указанное время.
        
        Args:
            alarm_id: ID аварии
            duration: Длительность продления
        
        Returns:
            Новое время исправления
        
        Raises:
            NotFoundError: Если авария не найдена
            ValidationError: Если новое время некорректно
        """
        alarm = self.get_alarm(alarm_id)
        
        # Парсим текущее время
        fix_time_value = alarm.get("fix_time")
        current_fix_time = safe_parse_datetime(fix_time_value)
        if not current_fix_time:
            raise ValidationError("Некорректное время исправления", "fix_time")
        
        # Вычисляем новое время
        new_fix_time = current_fix_time + duration
        
        if new_fix_time <= current_fix_time:
            raise ValidationError("Новое время должно быть позже текущего", "fix_time")
        
        # Обновляем
        alarm["fix_time"] = new_fix_time.isoformat()
        
        # Сбрасываем флаг напоминания
        if "reminder_sent_for" in alarm:
            del alarm["reminder_sent_for"]
        
        logger.info(f"Авария {alarm_id} продлена до {new_fix_time.isoformat()}")
        return new_fix_time
    
    def close_alarm(self, alarm_id: str) -> Dict:
        """
        Закрывает аварию.
        
        Args:
            alarm_id: ID аварии
        
        Returns:
            Данные закрытой аварии
        
        Raises:
            NotFoundError: Если авария не найдена
        """
        alarm = self.get_alarm(alarm_id)
        
        # Удаляем из активных
        del self.bot_state.active_alarms[alarm_id]
        
        logger.info(f"Авария {alarm_id} закрыта")
        return alarm
    
    def get_user_alarms(self, user_id: int) -> Dict[str, Dict]:
        """
        Получает все активные аварии пользователя.
        
        Args:
            user_id: ID пользователя
        
        Returns:
            Словарь {alarm_id: alarm_data}
        """
        return self.bot_state.get_user_active_alarms(user_id)
    
    def update_alarm_field(self, alarm_id: str, field: str, value: any) -> None:
        """
        Обновляет поле аварии.
        
        Args:
            alarm_id: ID аварии
            field: Название поля
            value: Новое значение
        
        Raises:
            NotFoundError: Если авария не найдена
        """
        alarm = self.get_alarm(alarm_id)
        alarm[field] = value
        logger.debug(f"Обновлено поле {field} для аварии {alarm_id}")
    
    async def create_jira_issue(
        self,
        issue: str,
        description: str,
        service: str,
        problem_level: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Создает задачу в Jira и возвращает данные задачи.
        
        Args:
            issue: Краткое описание проблемы (summary)
            description: Полное описание
            service: Затронутый сервис
            problem_level: Уровень проблемы (опционально)
        
        Returns:
            Словарь с данными созданной задачи (ключ 'key') или None при ошибке
        """
        from utils.create_jira_fa import create_failure_issue
        from domain.constants import PROBLEM_LEVEL_POTENTIAL, INFLUENCE_CLIENTS
        
        try:
            jira_response = await create_failure_issue(
                summary=issue,
                description=description,
                problem_level=problem_level or PROBLEM_LEVEL_POTENTIAL,
                problem_service=service,
                time_start_problem=datetime.now().strftime("%Y-%m-%d %H:%M"),
                influence=INFLUENCE_CLIENTS
            )
            
            if jira_response and 'key' in jira_response:
                logger.info(f"Задача в Jira создана: {jira_response['key']}")
                return jira_response
            else:
                logger.error("Не удалось получить ID задачи из Jira")
                return None
        except Exception as e:
            logger.error(f"Ошибка создания задачи в Jira: {e}", exc_info=True)
            return None
    
    def format_alarm_message(
        self,
        alarm_data: Dict,
        include_jira: bool = True
    ) -> str:
        """
        Форматирует сообщение об аварии для основного канала.
        
        Args:
            alarm_data: Данные аварии
            include_jira: Включать ли информацию о Jira
        
        Returns:
            Отформатированное сообщение
        """
        issue = alarm_data.get("issue", "не указано")
        service = alarm_data.get("service", "не указан")
        fix_time_str = alarm_data.get("fix_time", "")
        
        try:
            if isinstance(fix_time_str, str):
                fix_time = datetime.fromisoformat(fix_time_str)
            else:
                fix_time = fix_time_str
        except Exception:
            fix_time = datetime.now()
        
        message = (
            f"🚨 Технический сбой\n"
            f"• Проблема: {issue}\n"
            f"• Сервис: {service}\n"
            f"• Исправим до: {fix_time.strftime(DATETIME_FORMAT)}\n"
            f"• Мы уже работаем над устранением сбоя. Спасибо за ваше терпение и понимание!"
        )
        
        return message

