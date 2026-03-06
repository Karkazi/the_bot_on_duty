"""
Добавление комментария к задаче в Jira (REST API).
Используется при закрытии сбоя: архив чата MAX добавляется как комментарий в задачу FA-XXXX.
"""
import logging
from urllib.parse import urljoin

import aiohttp
from aiohttp import ClientTimeout

from config import CONFIG
from domain.constants import HTTP_REQUEST_TIMEOUT, HTTP_MAX_RETRIES

logger = logging.getLogger(__name__)


async def add_comment_to_jira_issue(jira_key: str, body: str) -> bool:
    """
    Добавляет комментарий к задаче в Jira.

    Args:
        jira_key: Ключ задачи (например, FA-1234).
        body: Текст комментария (plain text).

    Returns:
        True при успехе, False при ошибке.
    """
    jira_cfg = CONFIG.get("JIRA", {})
    login_url = (jira_cfg.get("LOGIN_URL") or "").strip()
    token = jira_cfg.get("TOKEN")
    if not login_url or not token:
        logger.warning("JIRA: LOGIN_URL или TOKEN не заданы, комментарий не добавлен")
        return False
    if not jira_key or not (body or "").strip():
        logger.warning("JIRA comment: пустой jira_key или body")
        return False

    base_url = urljoin(login_url, "/rest/api/2/")
    url = f"{base_url}issue/{jira_key}/comment"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {"body": (body or "").strip()}

    timeout = ClientTimeout(total=HTTP_REQUEST_TIMEOUT)
    for attempt in range(HTTP_MAX_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status in (200, 201):
                        logger.info("JIRA: комментарий добавлен к задаче %s", jira_key)
                        return True
                    err_text = await response.text()
                    logger.warning(
                        "JIRA add comment: status=%s, key=%s, body=%s",
                        response.status,
                        jira_key,
                        err_text[:300],
                    )
                    return False
        except Exception as e:
            logger.warning("JIRA add comment попытка %s: %s", attempt + 1, e)
    return False
