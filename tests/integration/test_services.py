"""
Integration тесты для сервисов.
"""
import pytest
from datetime import datetime, timedelta
from bot_state import BotState
from services.alarm_service import AlarmService
from services.maintenance_service import MaintenanceService
from utils.exceptions import ValidationError, NotFoundError


class TestAlarmService:
    """Integration тесты для AlarmService"""
    
    @pytest.mark.asyncio
    async def test_create_and_get_alarm(self, bot_state):
        """Тест создания и получения аварии"""
        service = AlarmService(bot_state)
        
        alarm_id = service.create_alarm(
            issue="Test issue",
            fix_time=datetime.now() + timedelta(hours=1),
            user_id=123,
            service="Test Service"
        )
        
        assert alarm_id in bot_state.active_alarms
        
        alarm = service.get_alarm(alarm_id)
        assert alarm["issue"] == "Test issue"
        assert alarm["user_id"] == 123
    
    @pytest.mark.asyncio
    async def test_extend_alarm(self, bot_state):
        """Тест продления аварии"""
        service = AlarmService(bot_state)
        
        fix_time = datetime.now() + timedelta(hours=1)
        alarm_id = service.create_alarm(
            issue="Test issue",
            fix_time=fix_time,
            user_id=123,
            service="Test Service"
        )
        
        new_fix_time = service.extend_alarm(alarm_id, timedelta(hours=1))
        assert new_fix_time > fix_time
        
        alarm = service.get_alarm(alarm_id)
        assert datetime.fromisoformat(alarm["fix_time"]) == new_fix_time
    
    @pytest.mark.asyncio
    async def test_close_alarm(self, bot_state):
        """Тест закрытия аварии"""
        service = AlarmService(bot_state)
        
        alarm_id = service.create_alarm(
            issue="Test issue",
            fix_time=datetime.now() + timedelta(hours=1),
            user_id=123,
            service="Test Service"
        )
        
        closed_alarm = service.close_alarm(alarm_id)
        assert alarm_id not in bot_state.active_alarms
        assert closed_alarm["issue"] == "Test issue"
    
    @pytest.mark.asyncio
    async def test_validation_error_on_create(self, bot_state):
        """Тест ошибки валидации при создании"""
        service = AlarmService(bot_state)
        
        with pytest.raises(ValidationError):
            service.create_alarm(
                issue="",  # Пустое описание
                fix_time=datetime.now() + timedelta(hours=1),
                user_id=123,
                service="Test Service"
            )
    
    @pytest.mark.asyncio
    async def test_not_found_error(self, bot_state):
        """Тест ошибки при отсутствии аварии"""
        service = AlarmService(bot_state)
        
        with pytest.raises(NotFoundError):
            service.get_alarm("nonexistent")


class TestMaintenanceService:
    """Integration тесты для MaintenanceService"""
    
    @pytest.mark.asyncio
    async def test_create_and_get_maintenance(self, bot_state):
        """Тест создания и получения работы"""
        service = MaintenanceService(bot_state)
        
        work_id = service.create_maintenance(
            description="Test work",
            start_time=datetime.now() + timedelta(hours=1),
            end_time=datetime.now() + timedelta(hours=2),
            user_id=123
        )
        
        assert work_id in bot_state.active_maintenances
        
        work = service.get_maintenance(work_id)
        assert work["description"] == "Test work"
        assert work["user_id"] == 123
    
    @pytest.mark.asyncio
    async def test_extend_maintenance(self, bot_state):
        """Тест продления работы"""
        service = MaintenanceService(bot_state)
        
        start_time = datetime.now() + timedelta(hours=1)
        end_time = datetime.now() + timedelta(hours=2)
        work_id = service.create_maintenance(
            description="Test work",
            start_time=start_time,
            end_time=end_time,
            user_id=123
        )
        
        new_end_time = service.extend_maintenance(work_id, end_time + timedelta(hours=1))
        assert new_end_time > end_time
        
        work = service.get_maintenance(work_id)
        assert datetime.fromisoformat(work["end_time"]) == new_end_time
    
    @pytest.mark.asyncio
    async def test_validation_error_on_create(self, bot_state):
        """Тест ошибки валидации при создании"""
        service = MaintenanceService(bot_state)
        
        with pytest.raises(ValidationError):
            service.create_maintenance(
                description="",  # Пустое описание
                start_time=datetime.now() + timedelta(hours=1),
                end_time=datetime.now() + timedelta(hours=2),
                user_id=123
            )

