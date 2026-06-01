"""
Закрытие/обновление полей FA-задачи в Jira при закрытии сбоя.

Сейчас требуется проставлять TimeEndProblem (кастомное поле Jira) в момент stop_alarm.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urljoin

import aiohttp
from aiohttp import ClientTimeout

from config import CONFIG
from domain.constants import HTTP_MAX_RETRIES, HTTP_RETRY_DELAY, HTTP_REQUEST_TIMEOUT, TIMEZONE_OFFSET

logger = logging.getLogger(__name__)

_FA_KEY_RE = re.compile(r"^FA-\d+$", re.IGNORECASE)


def resolve_jira_key(alarm_id: str, alarm_info: Optional[dict[str, Any]] = None) -> Optional[str]:
    """
    Ключ FA для Jira API: из state (jira_key) или из alarm_id вида FA-1234.
    """
    info = alarm_info or {}
    jk = (info.get("jira_key") or "").strip()
    if jk:
        return jk.upper() if _FA_KEY_RE.match(jk) else jk
    aid = (alarm_id or "").strip()
    if _FA_KEY_RE.match(aid):
        return aid.upper()
    return None


def _time_end_problem_field_key() -> str:
    """
    Ключ поля в Jira API.
    В Jira Petrovich поле «Время окончания сбоя» = customfield_13120.
    Можно переопределить через .env: JIRA_TIME_END_PROBLEM_FIELD=customfield_12345
    """
    return (os.getenv("JIRA_TIME_END_PROBLEM_FIELD", "") or "").strip() or "customfield_13120"


def _format_jira_datetime(dt: datetime) -> str:
    # Jira ожидает ISO8601 с timezone, как и TIME_START_PROBLEM в create_jira_fa.py
    return dt.strftime(f"%Y-%m-%dT%H:%M:00.000{TIMEZONE_OFFSET}")


async def set_time_end_problem(jira_key: str, closed_at: datetime) -> bool:
    jira_cfg = CONFIG.get("JIRA", {})
    login_url = (jira_cfg.get("LOGIN_URL") or "").strip()
    token = (jira_cfg.get("TOKEN") or "").strip()
    if not login_url or not token:
        logger.warning("JIRA: LOGIN_URL или TOKEN не заданы, поле TimeEndProblem не обновлено")
        return False
    if not jira_key:
        return False

    base_url = urljoin(login_url, "/rest/api/2/")
    url = f"{base_url}issue/{jira_key}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    field_key = _time_end_problem_field_key()
    payload = {"fields": {field_key: _format_jira_datetime(closed_at)}}

    timeout = ClientTimeout(total=HTTP_REQUEST_TIMEOUT)
    last_err = None
    for attempt in range(HTTP_MAX_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(url, json=payload, headers=headers) as r:
                    if r.status in (200, 204):
                        logger.info("JIRA: поле %s обновлено для %s", field_key, jira_key)
                        return True
                    err = await r.text()
                    last_err = f"status={r.status} body={err[:500]}"
                    # 4xx — без ретраев (обычно неверное поле/права/формат)
                    if 400 <= r.status < 500:
                        logger.warning("JIRA: не удалось обновить %s для %s: %s", field_key, jira_key, last_err)
                        return False
        except asyncio.CancelledError:
            raise
        except Exception as e:
            last_err = str(e)
            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))

    logger.warning("JIRA: не удалось обновить %s для %s (последняя ошибка: %s)", field_key, jira_key, last_err)
    return False

