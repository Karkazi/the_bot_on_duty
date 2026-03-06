"""
Утилита для проверки статуса задач в Jira.
"""
import asyncio
import logging
from typing import Optional
import aiohttp
from aiohttp import ClientTimeout, ClientError
from urllib.parse import urljoin

from config import CONFIG
from domain.constants import HTTP_REQUEST_TIMEOUT, HTTP_MAX_RETRIES, HTTP_RETRY_DELAY

logger = logging.getLogger(__name__)


async def get_jira_issue_status(jira_key: str) -> Optional[str]:
    """
    Получает статус задачи в Jira по ключу.
    
    Args:
        jira_key: Ключ задачи (например, "FA-123")
    
    Returns:
        str: Статус задачи (например, "Failure Fixed") или None в случае ошибки
    """
    if not CONFIG.get("JIRA", {}).get("LOGIN_URL") or not CONFIG.get("JIRA", {}).get("TOKEN"):
        logger.error("[JIRA_STATUS] Конфигурация JIRA не установлена")
        return None
    
    jira_url = CONFIG["JIRA"]["LOGIN_URL"].strip()
    base_url = urljoin(jira_url, '/rest/api/2/')
    
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {CONFIG["JIRA"]["TOKEN"]}'
    }
    
    timeout = ClientTimeout(total=HTTP_REQUEST_TIMEOUT)
    last_exception = None
    
    for attempt in range(HTTP_MAX_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{base_url}issue/{jira_key}",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        status_name = data["fields"]["status"]["name"]
                        logger.info(f"[JIRA_STATUS] Получен статус задачи {jira_key}: '{status_name}'")
                        return status_name
                    elif response.status == 404:
                        logger.warning(f"[JIRA_STATUS] Задача {jira_key} не найдена в Jira")
                        return None
                    elif response.status == 401:
                        logger.error("[JIRA_STATUS] Ошибка аутентификации в Jira")
                        return None
                    elif response.status == 403:
                        logger.error("[JIRA_STATUS] Ошибка доступа в Jira (нет прав)")
                        return None
                    else:
                        error_text = await response.text()
                        logger.warning(f"[JIRA_STATUS] Неожиданный статус {response.status}: {error_text}")
                        if 500 <= response.status < 600:
                            raise ClientError(f"Server error: {response.status}")
            
        except asyncio.TimeoutError:
            last_exception = f"Timeout при получении статуса (попытка {attempt + 1}/{HTTP_MAX_RETRIES})"
            logger.warning(last_exception)
            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))
        except ClientError as e:
            last_exception = f"Ошибка клиента: {str(e)} (попытка {attempt + 1}/{HTTP_MAX_RETRIES})"
            logger.warning(last_exception)
            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))
        except Exception as e:
            last_exception = f"Неожиданная ошибка: {str(e)} (попытка {attempt + 1}/{HTTP_MAX_RETRIES})"
            logger.error(last_exception, exc_info=True)
            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))
    
    logger.error(f"[JIRA_STATUS] Не удалось получить статус {jira_key} после {HTTP_MAX_RETRIES} попыток. Последняя ошибка: {last_exception}")
    return None

