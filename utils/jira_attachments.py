"""
Добавление вложений к задаче в Jira (REST API).
Используется при архивации чата MAX: текст — комментарий, файлы из чата — вложения к задаче.
"""
import logging
from pathlib import Path
from typing import List, Tuple
from urllib.parse import urljoin

import aiohttp

from config import CONFIG

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_SIZE_MB = 10


async def add_attachments_to_jira_issue(issue_key: str, file_paths: List[str]) -> Tuple[int, int]:
    """
    Добавляет вложения к задаче в Jira (POST rest/api/2/issue/{key}/attachments).
    file_paths — список путей к файлам (до 10 МБ каждый).
    Возвращает (успешно_добавлено, всего_попыток).
    """
    if not issue_key or not file_paths:
        return 0, 0
    jira_cfg = CONFIG.get("JIRA", {})
    login_url = (jira_cfg.get("LOGIN_URL") or "").strip()
    token = (jira_cfg.get("TOKEN") or "").strip()
    if not login_url or not token:
        logger.warning("JIRA: не заданы LOGIN_URL или TOKEN для вложений")
        return 0, len(file_paths)
    # LOGIN_URL может быть вида ".../login.jsp", поэтому строим URL от корня домена через абсолютный путь.
    url = urljoin(login_url, f"/rest/api/2/issue/{issue_key}/attachments")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Atlassian-Token": "no-check",
    }
    success_count = 0
    for path in file_paths:
        p = Path(path)
        if not p.is_file():
            logger.debug("Вложение не найдено: %s", path)
            continue
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > MAX_ATTACHMENT_SIZE_MB:
            logger.warning("Файл %s превышает %s МБ, пропуск", p.name, MAX_ATTACHMENT_SIZE_MB)
            continue
        try:
            body = p.read_bytes()
            data = aiohttp.FormData()
            data.add_field("file", body, filename=p.name, content_type="application/octet-stream")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        success_count += 1
                        logger.info("JIRA: вложение добавлено к %s: %s", issue_key, p.name)
                    else:
                        logger.warning(
                            "JIRA: вложение %s не добавлено: %s %s",
                            p.name,
                            resp.status,
                            (await resp.text())[:200],
                        )
        except Exception as e:
            logger.warning("JIRA: ошибка добавления вложения %s к %s: %s", p.name, issue_key, e)
    return success_count, len(file_paths)
