# utils/helpers.py
from aiogram import Bot
from config import CONFIG
from datetime import datetime, timedelta
import re
from typing import Optional
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.types import User

# Состояния теперь импортируются из domain/states.py
# Импорт здесь для обратной совместимости, но рекомендуется использовать domain.states напрямую


def parse_duration(duration_str: str) -> Optional[timedelta]:
    duration_str = duration_str.lower().strip()

    # Поддержка форматов: "через 1 час", "1 час", "30 мин", "через 2 дня"
    # Поддерживаем разные формы: минут/минуты, час/часа/часов, день/дня/дней
    pattern = r'(\d+[\.,]?\d*)\s*(минут[аы]?|мин|час[аов]?|дн[яей])'
    match = re.search(pattern, duration_str)

    if not match:
        return None

    value = float(match.group(1).replace(",", "."))
    unit = match.group(2)

    if 'минут' in unit or 'мин' in unit:
        return timedelta(minutes=value)
    elif 'час' in unit:
        return timedelta(hours=value)
    elif 'дн' in unit:  # день, дня, дней
        return timedelta(days=value)

    return None


async def get_user_name(user_id: int, bot: Bot) -> str:
    try:
        user = await bot.get_chat_member(CONFIG["TELEGRAM"]["ALARM_CHANNEL_ID"], user_id)
        if user.user.username:
            return f"@{user.user.username}"
        return f"[ID:{user_id}]"
    except Exception:
        return f"[ID:{user_id}]"


def is_admin(user_id: int) -> bool:
    from config import CONFIG
    return user_id in CONFIG.get("TELEGRAM", {}).get("ADMIN_IDS", [])


def is_superadmin(user_id: int) -> bool:
    from config import CONFIG
    return user_id in CONFIG.get("TELEGRAM", {}).get("SUPERADMIN_IDS", [])