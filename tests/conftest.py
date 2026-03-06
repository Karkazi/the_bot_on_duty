"""
Конфигурация pytest для тестов.

Перед импортом модулей, использующих config, выставляются минимальные переменные
окружения (или загружается .env.test), чтобы тесты не падали при отсутствии .env.
"""
import os
from pathlib import Path

# Минимальный конфиг для тестов — до любого импорта config/bot_state
_env_test = Path(__file__).resolve().parent.parent / ".env.test"
if _env_test.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_test)
else:
    for key, value in (
        ("TELEGRAM_TOKEN", "test-token"),
        ("ALARM_CHANNEL_ID", "-100123"),
        ("JIRA_TOKEN", "test-jira-token"),
        ("JIRA_LOGIN_URL", "https://jira.example.com/login.jsp"),
    ):
        os.environ.setdefault(key, value)

import pytest
import asyncio
from unittest.mock import Mock, MagicMock
from bot_state import BotState


@pytest.fixture
def event_loop():
    """Создает event loop для асинхронных тестов"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def bot_state():
    """Создает экземпляр BotState для тестов"""
    return BotState(use_queue=False)  # Без очереди для тестов


@pytest.fixture
def mock_bot():
    """Создает мок бота"""
    bot = Mock()
    bot.send_message = Mock(return_value=asyncio.coroutine(lambda: None)())
    return bot

