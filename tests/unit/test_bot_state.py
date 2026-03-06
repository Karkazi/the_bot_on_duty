"""
Unit тесты для модуля bot_state.
"""
import pytest
import asyncio
from datetime import datetime
from bot_state import BotState


class TestBotState:
    """Тесты для класса BotState"""
    
    @pytest.mark.asyncio
    async def test_create_alarm(self, bot_state):
        """Тест создания аварии"""
        alarm_id = "test_alarm"
        bot_state.active_alarms[alarm_id] = {
            "issue": "Test issue",
            "fix_time": datetime.now().isoformat(),
            "user_id": 123,
            "created_at": datetime.now().isoformat()
        }
        
        assert alarm_id in bot_state.active_alarms
        assert bot_state.active_alarms[alarm_id]["issue"] == "Test issue"
    
    @pytest.mark.asyncio
    async def test_get_user_alarms(self, bot_state):
        """Тест получения аварий пользователя"""
        user_id = 123
        bot_state.active_alarms["alarm1"] = {
            "issue": "Issue 1",
            "fix_time": datetime.now().isoformat(),
            "user_id": user_id,
            "created_at": datetime.now().isoformat()
        }
        bot_state.active_alarms["alarm2"] = {
            "issue": "Issue 2",
            "fix_time": datetime.now().isoformat(),
            "user_id": 456,  # Другой пользователь
            "created_at": datetime.now().isoformat()
        }
        
        user_alarms = bot_state.get_user_active_alarms(user_id)
        assert len(user_alarms) == 1
        assert "alarm1" in user_alarms
        assert "alarm2" not in user_alarms
    
    @pytest.mark.asyncio
    async def test_get_user_maintenances(self, bot_state):
        """Тест получения работ пользователя"""
        user_id = 123
        bot_state.active_maintenances["work1"] = {
            "description": "Work 1",
            "start_time": datetime.now().isoformat(),
            "end_time": datetime.now().isoformat(),
            "user_id": user_id,
            "created_at": datetime.now().isoformat()
        }
        bot_state.active_maintenances["work2"] = {
            "description": "Work 2",
            "start_time": datetime.now().isoformat(),
            "end_time": datetime.now().isoformat(),
            "user_id": 456,  # Другой пользователь
            "created_at": datetime.now().isoformat()
        }
        
        user_works = bot_state.get_user_active_maintenances(user_id)
        assert len(user_works) == 1
        assert "work1" in user_works
        assert "work2" not in user_works

