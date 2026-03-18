# services/confluence_service.py — загрузка и парсинг страницы календаря регламентных работ Confluence

import hashlib
import logging
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp

from config import CONFIG
from domain.constants import DATETIME_FORMAT

logger = logging.getLogger(__name__)

# Колонки таблицы: 0=тема, 1=начало, 2=окончание, 3=исполнитель, 4=описание, 5=недоступные сервисы, 6=каналы
_COL_START, _COL_END = 1, 2
_COL_OWNER, _COL_DESCRIPTION, _COL_SERVICES, _COL_CHANNELS = 3, 4, 5, 6


def _page_id_from_url(url: str) -> Optional[str]:
    if not (url or url.strip()):
        return None
    parsed = urlparse(url.strip())
    qs = parse_qs(parsed.query)
    ids = qs.get("pageId") or qs.get("pageid")
    if ids and isinstance(ids, list) and ids[0]:
        return str(ids[0]).strip()
    return None


def get_confluence_page_id() -> str:
    """ID страницы календаря: из CONFIG или pageId из CONFLUENCE_TARGET_URL."""
    conf = CONFIG.get("CONFLUENCE", {}) or {}
    raw = (conf.get("WORKS_PAGE_ID") or "").strip()
    if raw:
        return raw
    target = (conf.get("TARGET_URL") or "").strip()
    pid = _page_id_from_url(target)
    if pid:
        return pid
    return "346932621"


def _strip_cell(html: str) -> str:
    text = re.sub(r"<time\s+datetime=\"([^\"]+)\"\s*/>", r"\1 ", html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    return " ".join((text or "").split()).strip()


def _is_row_empty(row_html: str) -> bool:
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL | re.IGNORECASE)
    for cell in cells:
        if _strip_cell(cell):
            return False
    return True


def _make_work_id(description: str, start_time_str: str, end_time_str: str) -> str:
    key = f"{description.strip()}|{start_time_str}|{end_time_str}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _parse_row(row_html: str) -> Optional[dict]:
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL | re.IGNORECASE)
    if len(cells) <= _COL_CHANNELS:
        return None
    date_match = re.search(r'<time\s+datetime="(\d{4}-\d{2}-\d{2})"', row_html)
    date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")
    raw_start = _strip_cell(cells[_COL_START])
    raw_end = _strip_cell(cells[_COL_END])
    start_part = raw_start.split()[-1] if raw_start else "00:00"
    end_part = raw_end.split()[-1] if raw_end else "00:00"
    if ":" not in start_part:
        start_part = "00:00"
    if ":" not in end_part:
        end_part = "00:00"
    try:
        dt_start = datetime.strptime(f"{date_str} {start_part}", "%Y-%m-%d %H:%M")
        dt_end = datetime.strptime(f"{date_str} {end_part}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    description = _strip_cell(cells[_COL_DESCRIPTION]) or "не указано"
    unavailable_services = _strip_cell(cells[_COL_SERVICES]) or "не указано"
    owner = _strip_cell(cells[_COL_OWNER]) if len(cells) > _COL_OWNER else ""
    notify = _strip_cell(cells[_COL_CHANNELS]) if len(cells) > _COL_CHANNELS else ""
    start_time_str = dt_start.strftime(DATETIME_FORMAT)
    end_time_str = dt_end.strftime(DATETIME_FORMAT)
    work_id = _make_work_id(description, start_time_str, end_time_str)
    return {
        "work_id": work_id,
        "description": description,
        "start_time_str": start_time_str,
        "end_time_str": end_time_str,
        "unavailable_services": unavailable_services,
        "owner": owner,
        "notify": notify,
        "start_time": dt_start,
        "end_time": dt_end,
    }


def parse_works_table(storage: str) -> List[dict]:
    """Парсит body.storage: все непустые строки таблицы. Возвращает список dict с work_id, notify и полями для оповещения."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", storage, flags=re.DOTALL | re.IGNORECASE)
    result = []
    for row_html in rows:
        if _is_row_empty(row_html):
            continue
        row = _parse_row(row_html)
        if row:
            result.append(row)
    return result


async def append_work_to_confluence_table(page_id: str, work: dict) -> bool:
    """
    Добавляет новую строку в таблицу регламентных работ Confluence.
    Структура колонок: Объект | Начало | Окончание | ФИО | Описание тех. | Описание польз. | Сервисы | Каналы.
    """
    conf = CONFIG.get("CONFLUENCE", {}) or {}
    login_url = (conf.get("LOGIN_URL") or "").strip()
    token = (conf.get("TOKEN") or "").strip()
    username = (conf.get("USERNAME") or "").strip()
    password = (conf.get("PASSWORD") or "").strip()
    if not login_url or not page_id:
        logger.warning("[CONF_WRITE] Confluence не настроен (нет login_url или page_id)")
        return False

    base = urljoin(login_url, "/")
    get_url = urljoin(base, f"rest/api/content/{page_id}?expand=body.storage,version")
    headers: dict = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    auth = aiohttp.BasicAuth(username, password) if (username and password and not token) else None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                get_url, headers=headers or None, auth=auth, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    logger.warning("[CONF_WRITE] Ошибка чтения страницы: status=%s", resp.status)
                    return False
                page_data = await resp.json()
    except Exception as e:
        logger.warning("[CONF_WRITE] Ошибка при чтении страницы: %s", e, exc_info=True)
        return False

    version_num = (page_data.get("version") or {}).get("number", 1)
    title = page_data.get("title", "")
    storage_val = ((page_data.get("body") or {}).get("storage") or {}).get("value") or ""

    # Формируем новую строку
    start_dt = work["start_time"] if isinstance(work["start_time"], datetime) else datetime.fromisoformat(str(work["start_time"]))
    end_dt = work["end_time"] if isinstance(work["end_time"], datetime) else datetime.fromisoformat(str(work["end_time"]))
    start_date_iso = start_dt.strftime("%Y-%m-%d")
    start_time_hm = start_dt.strftime("%H:%M")
    end_date_iso = end_dt.strftime("%Y-%m-%d")
    end_time_hm = end_dt.strftime("%H:%M")

    description = (work.get("description") or "").replace("<", "&lt;").replace(">", "&gt;")
    tech_desc = (work.get("cal_tech_description") or description).replace("<", "&lt;").replace(">", "&gt;")
    services = (work.get("unavailable_services") or "не указано").replace("<", "&lt;").replace(">", "&gt;")
    owner = (work.get("owner") or "Дежурный СА").replace("<", "&lt;").replace(">", "&gt;")
    notify_ch = (work.get("cal_notify") or "Нет").replace("<", "&lt;").replace(">", "&gt;")

    new_row = (
        f'<tr>'
        f'<td><p>{description}</p></td>'
        f'<td><p><time datetime="{start_date_iso}" />{start_time_hm}</p></td>'
        f'<td><p><time datetime="{end_date_iso}" />{end_time_hm}</p></td>'
        f'<td><p>{owner}</p></td>'
        f'<td><p>{tech_desc}</p></td>'
        f'<td><p>{description}</p></td>'
        f'<td><p>{services}</p></td>'
        f'<td><p>{notify_ch}</p></td>'
        f'</tr>'
    )

    # Вставляем перед последним </tbody>, иначе перед </table>
    last_tbody = storage_val.rfind("</tbody>")
    if last_tbody >= 0:
        new_storage = storage_val[:last_tbody] + new_row + storage_val[last_tbody:]
    else:
        last_table = storage_val.rfind("</table>")
        if last_table >= 0:
            new_storage = storage_val[:last_table] + new_row + storage_val[last_table:]
        else:
            logger.warning("[CONF_WRITE] Не удалось найти таблицу в storage страницы")
            return False

    put_url = urljoin(base, f"rest/api/content/{page_id}")
    put_payload = {
        "version": {"number": version_num + 1},
        "type": "page",
        "title": title,
        "body": {
            "storage": {
                "value": new_storage,
                "representation": "storage",
            }
        },
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                put_url, json=put_payload, headers=headers or None, auth=auth,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status not in (200, 201):
                    body_text = await resp.text()
                    logger.warning("[CONF_WRITE] Ошибка обновления: status=%s body=%s", resp.status, body_text[:300])
                    return False
        logger.info("[CONF_WRITE] Новая запись добавлена на страницу %s", page_id)
        return True
    except Exception as e:
        logger.warning("[CONF_WRITE] Ошибка при записи страницы: %s", e, exc_info=True)
        return False


async def fetch_page_storage(page_id: str) -> Optional[str]:
    """Загружает body.storage.value страницы Confluence через REST API. Возвращает None при ошибке."""
    conf = CONFIG.get("CONFLUENCE", {}) or {}
    login_url = (conf.get("LOGIN_URL") or "").strip()
    token = (conf.get("TOKEN") or "").strip()
    username = (conf.get("USERNAME") or "").strip()
    password = (conf.get("PASSWORD") or "").strip()
    if not login_url or not page_id:
        return None
    base = urljoin(login_url, "/")
    url = urljoin(base, f"rest/api/content/{page_id}?expand=body.storage")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    auth = aiohttp.BasicAuth(username, password) if (username and password and not token) else None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers or None, auth=auth, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("[CONF_MAINT] Confluence fetch: status=%s", resp.status)
                    return None
                data = await resp.json()
    except Exception as e:
        logger.warning("[CONF_MAINT] Confluence fetch error: %s", e, exc_info=True)
        return None
    storage = (data.get("body") or {}).get("storage") or {}
    return (storage.get("value") or "") if isinstance(storage, dict) else None
