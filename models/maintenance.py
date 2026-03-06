"""
Pydantic модели для валидации данных регламентных работ.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class MaintenanceCreateRequest(BaseModel):
    """Модель для создания регламентной работы"""
    description: str = Field(..., min_length=1, max_length=2000, description="Описание работ")
    start_time: datetime = Field(..., description="Время начала")
    end_time: datetime = Field(..., description="Время окончания")
    unavailable_services: str = Field("не указано", description="Недоступные сервисы")
    
    @field_validator('start_time')
    @classmethod
    def validate_start_time(cls, v: datetime) -> datetime:
        """Проверяет, что время начала не в прошлом"""
        if v < datetime.now():
            raise ValueError("Время начала не может быть в прошлом")
        return v
    
    @model_validator(mode='after')
    def validate_times(self) -> 'MaintenanceCreateRequest':
        """Проверяет, что время окончания позже начала"""
        if self.end_time <= self.start_time:
            raise ValueError("Время окончания должно быть позже начала")
        return self


class MaintenanceExtendRequest(BaseModel):
    """Модель для продления работы"""
    work_id: str = Field(..., min_length=1, description="ID работы")
    new_end_time: Optional[datetime] = Field(None, description="Новое время окончания")
    duration_minutes: Optional[int] = Field(None, gt=0, description="Длительность продления в минутах")
    
    @model_validator(mode='after')
    def validate_extend_params(self) -> 'MaintenanceExtendRequest':
        """Проверяет, что указано либо новое время, либо длительность"""
        if not self.new_end_time and not self.duration_minutes:
            raise ValueError("Необходимо указать либо новое время окончания, либо длительность продления")
        if self.new_end_time and self.duration_minutes:
            raise ValueError("Укажите либо новое время окончания, либо длительность продления, но не оба параметра")
        return self


class MaintenanceResponse(BaseModel):
    """Модель ответа с данными работы"""
    work_id: str
    description: str
    start_time: datetime
    end_time: datetime
    user_id: int
    created_at: datetime
    unavailable_services: str

