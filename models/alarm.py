"""
Pydantic модели для валидации данных аварий.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class AlarmCreateRequest(BaseModel):
    """Модель для создания аварии"""
    issue: str = Field(..., min_length=1, max_length=2000, description="Описание проблемы")
    fix_time: datetime = Field(..., description="Время исправления")
    service: str = Field(..., min_length=1, description="Затронутый сервис")
    jira_key: Optional[str] = Field(None, description="Ключ задачи в Jira")
    has_jira: bool = Field(False, description="Есть ли задача в Jira")
    scm_topic_id: Optional[int] = Field(None, description="ID темы в SCM канале")
    
    @field_validator('fix_time')
    @classmethod
    def validate_fix_time(cls, v: datetime) -> datetime:
        """Проверяет, что время исправления не в прошлом"""
        if v < datetime.now():
            raise ValueError("Время исправления не может быть в прошлом")
        return v


class AlarmExtendRequest(BaseModel):
    """Модель для продления аварии"""
    alarm_id: str = Field(..., min_length=1, description="ID аварии")
    duration_minutes: int = Field(..., gt=0, description="Длительность продления в минутах")
    
    @field_validator('duration_minutes')
    @classmethod
    def validate_duration(cls, v: int) -> int:
        """Проверяет разумность длительности"""
        if v > 1440:  # 24 часа
            raise ValueError("Длительность продления не может превышать 24 часа")
        return v


class AlarmResponse(BaseModel):
    """Модель ответа с данными аварии"""
    alarm_id: str
    issue: str
    fix_time: datetime
    user_id: int
    created_at: datetime
    jira_key: Optional[str] = None
    has_jira: bool = False
    scm_topic_id: Optional[int] = None

