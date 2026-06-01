"""
Пути приложения: не зависят от текущей рабочей директории процесса (cwd).

Каталог данных: BOT_APP_DATA_DIR / DATA_DIR в .env, иначе <корень проекта>/data/
(см. utils.paths_bootstrap).
"""
from pathlib import Path

from utils.paths_bootstrap import APP_DATA_DIR, PROJECT_ROOT

# Файл логов — внутри каталога данных (удобно монтировать один volume в Docker)
BOT_LOG_FILE = APP_DATA_DIR / "logs" / "bot.log"

__all__ = ["PROJECT_ROOT", "APP_DATA_DIR", "BOT_LOG_FILE"]
