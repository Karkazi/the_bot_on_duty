"""
Каталог данных приложения и TMPDIR для tempfile.

Импортируется через utils.app_paths (или явно первым в main.py), чтобы:
- state.json, логи, архивы и временные файлы жили в одном месте (по умолчанию <проект>/data/);
- на сервере — в /root/the_bot_on_duty_2/data, а не в /root/.

Переменные окружения:
- BOT_APP_DATA_DIR — абсолютный путь к каталогу данных (приоритет);
- DATA_DIR — то же (алиас);
- BOT_ENV_FILE — путь к .env (если не в корне кода);
- BOT_PROJECT_ROOT — корень проекта на сервере (для поиска .env).

Перед чтением override подгружается .env, чтобы BOT_APP_DATA_DIR учитывался при раннем import.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Стандартный путь деплоя на Linux-сервере (см. docs/docker_update_instructions.md)
DEFAULT_SERVER_PROJECT_ROOT = Path("/root/the_bot_on_duty_2")
DEFAULT_SERVER_DATA_DIR = DEFAULT_SERVER_PROJECT_ROOT / "data"
DEFAULT_DOCKER_DATA_DIR = Path("/app/data")


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    candidates: list[Path] = []
    env_override = (os.environ.get("BOT_ENV_FILE") or "").strip()
    if env_override:
        candidates.append(Path(env_override).expanduser())
    project_override = (os.environ.get("BOT_PROJECT_ROOT") or "").strip()
    if project_override:
        candidates.append(Path(project_override).expanduser() / ".env")
    candidates.append(PROJECT_ROOT / ".env")
    if DEFAULT_SERVER_PROJECT_ROOT != PROJECT_ROOT:
        candidates.append(DEFAULT_SERVER_PROJECT_ROOT / ".env")

    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        load_dotenv(resolved, override=False)


_load_env_files()


def _normalize_data_dir(path: Path) -> Path:
    """Не писать в /root напрямую — только в подкаталог проекта."""
    resolved = path.expanduser().resolve()
    if resolved == Path("/root"):
        fallback = DEFAULT_SERVER_DATA_DIR
        print(
            f"WARNING: BOT_APP_DATA_DIR=/root — перенаправляю данные в {fallback}",
            file=sys.stderr,
        )
        return fallback.resolve()
    return resolved


def _resolve_app_data_dir() -> Path:
    override = (os.environ.get("BOT_APP_DATA_DIR") or os.environ.get("DATA_DIR") or "").strip()
    if override:
        return _normalize_data_dir(Path(override))

    if Path("/.dockerenv").is_file():
        return DEFAULT_DOCKER_DATA_DIR.resolve()

    if (DEFAULT_SERVER_PROJECT_ROOT / "main.py").is_file():
        return DEFAULT_SERVER_DATA_DIR.resolve()

    return (PROJECT_ROOT / "data").resolve()


APP_DATA_DIR = _resolve_app_data_dir()


def _ensure_runtime_dirs() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (APP_DATA_DIR / "tmp").mkdir(parents=True, exist_ok=True)
    (APP_DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (APP_DATA_DIR / "archive" / "alarms").mkdir(parents=True, exist_ok=True)


_ensure_runtime_dirs()
os.environ.setdefault("TMPDIR", str(APP_DATA_DIR / "tmp"))
os.environ.setdefault("BOT_APP_DATA_DIR", str(APP_DATA_DIR))
