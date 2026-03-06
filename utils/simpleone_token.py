"""
Получение нового Bearer-токена SimpleOne по логину и паролю.
Используется для автоматического обновления токена (срок жизни ~120 минут).
Логика соответствует скрипту get_token.py из проекта SimpleOne.
Прокси задаётся через SIMPLEONE_PROXY_URL в .env (опционально).
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

LOGIN_ENDPOINT = "/v1/auth/login"


def _try_login(
    base_url: str,
    username: str,
    password: str,
    payload: dict,
    use_form_data: bool = False,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Одна попытка входа. Возвращает (success, token, error_message).
    """
    url = f"{base_url.rstrip('/')}{LOGIN_ENDPOINT}"
    if use_form_data:
        headers = {}
        data = payload
        send_kw = {"data": data, "headers": headers}
    else:
        headers = {"Content-Type": "application/json"}
        send_kw = {"json": payload, "headers": headers}

    proxies = None
    proxy_url = os.getenv("SIMPLEONE_PROXY_URL", "").strip()
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    try:
        response = requests.post(url, timeout=30, proxies=proxies, **send_kw)
        if response.status_code != 200:
            try:
                err = response.json()
                msg = (err.get("errors") or [{}])[0].get("message", response.text[:200])
            except Exception:
                msg = response.text[:200]
            return (False, None, msg)

        data = response.json()
        token = None
        if isinstance(data.get("data"), dict) and "auth_key" in (data.get("data") or {}):
            token = data["data"]["auth_key"]
        if not token and "auth_key" in data:
            token = data["auth_key"]
        if not token:
            for key in ("token", "access_token", "bearer_token", "auth_token"):
                if data.get(key):
                    token = data[key]
                    break
        if token:
            return (True, token, None)
        return (False, None, "Токен не найден в ответе")
    except requests.RequestException as e:
        return (False, None, str(e))
    except json.JSONDecodeError as e:
        return (False, None, f"JSON: {e}")


def get_new_token(base_url: str, username: str, password: str) -> Optional[str]:
    """
    Получает новый Bearer-токен через SimpleOne /v1/auth/login.
    Пробует варианты логина (с доменом std\\ и без) и форматы (JSON / form-data).

    Args:
        base_url: Базовый URL SimpleOne (например https://simpleone.example.com).
        username: Логин (например std\\user или user).
        password: Пароль.

    Returns:
        Новый токен или None при ошибке.
    """
    if not username or not password:
        logger.warning("SimpleOne: для обновления токена нужны USERNAME и PASSWORD")
        return None

    variants = [username]
    if "\\" not in username and "/" not in username and "@" not in username:
        variants.extend([f"std\\{username}", f"std/{username}"])
    elif "\\" in username:
        variants.append(username.replace("\\", "/"))
        variants.append(username.split("\\")[-1])

    seen = set()
    variants = [x for x in variants if not (x in seen or seen.add(x))]

    payloads = [
        {"username": None, "password": password},
        {"user": None, "password": password},
    ]

    for u in variants:
        for pt in payloads:
            payload = {k: (u if v is None else v) for k, v in pt.items()}
            success, token, err = _try_login(base_url, u, password, payload, use_form_data=False)
            if success:
                logger.info("SimpleOne: новый токен получен по логину/паролю")
                return token
            if err and "password is not specified" in (err or "").lower():
                success, token, _ = _try_login(base_url, u, password, payload, use_form_data=True)
                if success:
                    logger.info("SimpleOne: новый токен получен (form-data)")
                    return token

    logger.warning("SimpleOne: не удалось получить токен: %s", err)
    return None


def update_env_token(token: str, env_path: Optional[Path] = None) -> bool:
    """
    Обновляет только SIMPLEONE_TOKEN в файле .env, не трогая остальные переменные.

    Returns:
        True если запись прошла успешно.
    """
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        logger.debug("Файл .env не найден для обновления токена: %s", env_path)
        return False

    try:
        lines = []
        found = False
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("SIMPLEONE_TOKEN="):
                    lines.append(f"SIMPLEONE_TOKEN={token}\n")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"\nSIMPLEONE_TOKEN={token}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info("Токен SimpleOne обновлён в файле .env")
        return True
    except Exception as e:
        logger.warning("Не удалось обновить SIMPLEONE_TOKEN в .env: %s", e)
        return False
