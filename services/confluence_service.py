# services/confluence_service.py — загрузка и парсинг страницы календаря регламентных работ Confluence

import hashlib
import asyncio
import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp

from config import CONFIG
from domain.constants import DATETIME_FORMAT
from utils.bot_time import bot_now_naive

logger = logging.getLogger(__name__)

# Колонки таблицы могут менять порядок/состав по кварталам, поэтому ищем индексы по заголовкам.
# Минимально ожидаемые: Начало, Окончание, (Описание/Тема), Недоступные сервисы, Оповещения.
_HEADER_ALIASES = {
    "start": ("начало", "дата и время начала", "start"),
    "end": ("окончание", "конец", "дата и время окончания", "end"),
    "owner": ("исполнитель", "ответственный", "фио", "owner"),
    "description": ("описание", "тема", "объект", "работы", "work", "subject"),
    "services": ("недоступно", "недоступные сервисы", "сервисы", "services"),
    "notify": (
        "оповещения",
        "каналы",
        "уведомления",
        "информирование",
        "петлокал",
        "мах",
        "max",
        "notify",
    ),
    "inform_at": ("дата и время информирования", "информирование", "inform"),
}

# Страницы без строки <th>: тема | начало | конец | информирование | ответственный | примечание | сервисы | каналы | …
_WIDE_10_COL = {
    "start": 1,
    "end": 2,
    "owner": 4,
    "description": 0,
    "services": 6,
    "notify": 7,
    "inform_at": 3,
}


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


def _parse_label_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Пытается извлечь (space, label) из URL вида:
    https://.../label/PUB/calendaritactual
    """
    if not url or not url.strip():
        return None
    parsed = urlparse(url.strip())
    parts = [p for p in parsed.path.split("/") if p]
    # ищем подпоследовательность: label/{space}/{label}
    for i in range(len(parts) - 2):
        if parts[i].lower() == "label":
            space = parts[i + 1]
            label = parts[i + 2]
            if space and label:
                return space, label
    return None


async def fetch_page_ids_by_label(space: str, label: str) -> List[str]:
    """
    Получает список pageId страниц по label+space через Confluence REST CQL.
    """
    conf = CONFIG.get("CONFLUENCE", {}) or {}
    login_url = (conf.get("LOGIN_URL") or "").strip()
    token = (conf.get("TOKEN") or "").strip()
    username = (conf.get("USERNAME") or "").strip()
    password = (conf.get("PASSWORD") or "").strip()

    if not login_url or not (space and label):
        return []

    base = urljoin(login_url, "/")
    search_url = urljoin(base, "rest/api/content/search")

    headers: dict = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    auth = aiohttp.BasicAuth(username, password) if (username and password and not token) else None

    # Экранируем двойные кавычки в значениях CQL
    label_esc = str(label).replace('"', '\\"')
    space_esc = str(space).replace('"', '\\"')
    cql = f'type=page AND label="{label_esc}" AND space="{space_esc}"'

    limit = 50
    start = 0
    page_ids: List[str] = []

    async with aiohttp.ClientSession() as session:
        while True:
            params = {"cql": cql, "limit": limit, "start": start}
            async with session.get(
                search_url,
                params=params,
                headers=headers or None,
                auth=auth,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(
                        "[CONF] fetch_page_ids_by_label error: status=%s cql=%s body=%s",
                        resp.status,
                        cql,
                        body[:300],
                    )
                    return page_ids
                data = await resp.json()

            results = data.get("results") or []
            for item in results:
                pid = item.get("id")
                if pid is not None:
                    page_ids.append(str(pid))

            size = data.get("size")
            if not results:
                break
            if isinstance(size, int):
                if start + len(results) >= size:
                    break

            start += len(results)

    # Убираем дубликаты при сохранении порядка
    seen = set()
    uniq: List[str] = []
    for pid in page_ids:
        if pid not in seen:
            uniq.append(pid)
            seen.add(pid)
    return uniq


async def get_confluence_calendar_page_ids() -> List[str]:
    """
    Возвращает список pageId для календаря.
    Если задан LABEL_URL/LABEL_NAME — ищем все страницы по label и space.
    Иначе — возвращаем одиночный pageId (как раньше).
    """
    conf = CONFIG.get("CONFLUENCE", {}) or {}
    label_url = (conf.get("LABEL_URL") or "").strip()
    label_name = (conf.get("LABEL_NAME") or "").strip()
    label_space = (conf.get("LABEL_SPACE") or "").strip()

    parsed = _parse_label_url(label_url) if label_url else None
    if parsed:
        label_space, label_name = parsed[0], parsed[1]

    if label_name:
        if not label_space:
            # если space не задан, берём из URL-парсинга; иначе считаем ошибку конфигурации
            logger.warning("[CONF] LABEL_SPACE не задан, и URL не распарсился — не ищем pages по label")
            return [get_confluence_page_id()]
        ids = await fetch_page_ids_by_label(label_space, label_name)
        return ids if ids else [get_confluence_page_id()]

    return [get_confluence_page_id()]


def _strip_cell(html: str) -> str:
    # Confluence иногда хранит значения иконками (<img alt="...">).
    # Сначала вытаскиваем alt, чтобы после удаления тегов оно не потерялось.
    html = re.sub(r'<img[^>]*alt="([^"]+)"[^>]*>', r"\1 ", html, flags=re.IGNORECASE)
    html = re.sub(r"<img[^>]*alt='([^']+)'[^>]*>", r"\1 ", html, flags=re.IGNORECASE)
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

def _norm_header(s: str) -> str:
    return " ".join((s or "").strip().lower().replace("\u00a0", " ").split())


def _extract_table_header_indexes(storage: str) -> dict:
    """
    Возвращает mapping name->index по первой строке с <th>.
    Если заголовки не найдены, возвращает пустой dict.
    """
    header_tr = re.search(r"<tr[^>]*>.*?<th[^>]*>.*?</th>.*?</tr>", storage, flags=re.DOTALL | re.IGNORECASE)
    if not header_tr:
        return {}
    ths = re.findall(r"<th[^>]*>(.*?)</th>", header_tr.group(0), flags=re.DOTALL | re.IGNORECASE)
    if not ths:
        return {}
    labels = [_norm_header(_strip_cell(th)) for th in ths]
    idx: dict[str, int] = {}
    for name, aliases in _HEADER_ALIASES.items():
        for i, label in enumerate(labels):
            if any(a in label for a in aliases):
                idx[name] = i
                break
    return idx


def _try_parse_inform_at(raw: str) -> Optional[datetime]:
    s = " ".join((raw or "").strip().split())
    if not s:
        return None
    # Частые форматы: 26.03.2026 10:00, 2026-03-26 10:00, с секундами
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    # Иногда Confluence отдаёт ISO (например из <time datetime="...">)
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


_RE_DOT_DATETIME = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}\b")
_RE_ISO_DATETIME = re.compile(r"\b\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}\b")


def _detect_inform_at_column_index(storage: str) -> Optional[int]:
    """
    Пытается найти индекс колонки «Дата и время Информирования» по формату дат в ячейках.
    Это позволяет не зависеть от того, есть ли в Confluence <th> и как именно размечены заголовки.
    """
    # ограничимся первыми N строками внутри tbody, чтобы не тормозить
    m = re.search(r"<tbody[^>]*>(.*?)</tbody>", storage, flags=re.DOTALL | re.IGNORECASE)
    body = m.group(1) if m else storage
    tr_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body, flags=re.DOTALL | re.IGNORECASE)
    if not tr_rows:
        return None

    # 1) Сначала определяем кандидатов start/end как две самые "датные" dot-колонки
    dot_scores: dict[int, int] = {}
    iso_scores: dict[int, int] = {}
    max_cols = 0

    for row_html in tr_rows[:40]:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL | re.IGNORECASE)
        if not tds:
            continue
        max_cols = max(max_cols, len(tds))
        for i, td_html in enumerate(tds):
            cell = _strip_cell(td_html)
            if not cell:
                continue
            if _RE_DOT_DATETIME.search(cell):
                dot_scores[i] = dot_scores.get(i, 0) + 1
            elif _RE_ISO_DATETIME.search(cell):
                iso_scores[i] = iso_scores.get(i, 0) + 1

    if max_cols == 0:
        return None

    start_end_candidates = {i for i, _ in sorted(dot_scores.items(), key=lambda kv: kv[1], reverse=True)[:2]}
    if not start_end_candidates:
        # деградация: попробуем по iso
        start_end_candidates = {i for i, _ in sorted(iso_scores.items(), key=lambda kv: kv[1], reverse=True)[:2]}

    # 2) Дальше для каждого оставшегося столбца считаем, где распарсенная дата отличается от start/end
    def _parse_dt_from_cell(td_html: str) -> Optional[datetime]:
        date_match = re.search(r'<time\s+datetime="(\d{4}-\d{2}-\d{2})"', td_html, flags=re.IGNORECASE)
        if not date_match:
            return None
        date_str = date_match.group(1)
        raw = _strip_cell(td_html)
        time_part = raw.split()[-1] if raw else ""
        if ":" not in time_part:
            return None
        try:
            return datetime.strptime(f"{date_str} {time_part}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None

    diff_counts: dict[int, int] = {}
    dot_cell_counts: dict[int, int] = {}

    for row_html in tr_rows[:60]:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL | re.IGNORECASE)
        if not tds:
            continue

        # старт/конец
        start_dt_list = []
        for idx in start_end_candidates:
            if idx < len(tds):
                dt = _parse_dt_from_cell(tds[idx])
                if dt:
                    start_dt_list.append(dt)

        if not start_dt_list:
            continue

        for i, td_html in enumerate(tds):
            if i in start_end_candidates:
                continue
            cell_text = _strip_cell(td_html)
            if not cell_text:
                continue
            if _RE_DOT_DATETIME.search(cell_text) or _RE_ISO_DATETIME.search(cell_text):
                dot_cell_counts[i] = dot_cell_counts.get(i, 0) + 1
                dt_inform = _try_parse_inform_at(cell_text)
                if not dt_inform:
                    continue
                if all(dt_inform != dt for dt in start_dt_list):
                    diff_counts[i] = diff_counts.get(i, 0) + 1

    if diff_counts:
        # дополнительно: выбираем достаточно "занятой" столбец
        best_i, _ = max(diff_counts.items(), key=lambda kv: kv[1])
        return best_i

    # 3) Если не нашли отличающийся столбец, возвращаем лучший dot (для совместимости)
    if dot_scores:
        best = max(dot_scores.items(), key=lambda kv: kv[1])[0]
        return best
    if iso_scores:
        best = max(iso_scores.items(), key=lambda kv: kv[1])[0]
        return best
    return None


def _parse_row(row_html: str, col_idx: dict) -> Optional[dict]:
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL | re.IGNORECASE)
    # Требуем хотя бы максимальный индекс из найденных колонок (если заголовков нет — используем fallback ниже).
    max_required = max(col_idx.values()) if col_idx else 6
    if len(cells) <= max_required:
        return None
    # Fallback на старую схему: 1=начало, 2=конец, 3=исполнитель, 4=описание, 5=сервисы, 6=каналы
    start_i = col_idx.get("start", 1)
    end_i = col_idx.get("end", 2)
    owner_i = col_idx.get("owner", 3)
    desc_i = col_idx.get("description", 4)
    services_i = col_idx.get("services", 5)
    notify_i = col_idx.get("notify", 6)
    inform_i = col_idx.get("inform_at")

    # Парсим start/end строго из соответствующих td:
    # - дата: берём из <time datetime="..."> внутри ячейки
    # - время: берём последнюю часть (обычно HH:MM)
    dt_start = None
    dt_end = None

    if start_i < len(cells):
        start_cell_html = cells[start_i]
        start_date_match = re.search(r'<time\s+datetime="(\d{4}-\d{2}-\d{2})"', start_cell_html, flags=re.IGNORECASE)
        raw_start = _strip_cell(start_cell_html)

        # Дата из <time datetime="YYYY-MM-DD">; если тега нет — пытаемся найти дату в тексте ячейки.
        start_date_str = start_date_match.group(1) if start_date_match else None
        if not start_date_str and raw_start:
            m_iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw_start)
            m_dot = re.search(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b", raw_start)
            if m_iso:
                start_date_str = m_iso.group(1)
            elif m_dot:
                try:
                    start_date_str = datetime.strptime(m_dot.group(1), "%d.%m.%Y").strftime("%Y-%m-%d")
                except ValueError:
                    start_date_str = None

        start_part = raw_start.split()[-1] if raw_start else "00:00"
        if ":" not in start_part:
            start_part = "00:00"
        if start_date_str:
            try:
                dt_start = datetime.strptime(f"{start_date_str} {start_part}", "%Y-%m-%d %H:%M")
            except ValueError:
                dt_start = None
        else:
            dt_start = None

    if end_i < len(cells):
        end_cell_html = cells[end_i]
        end_date_match = re.search(r'<time\s+datetime="(\d{4}-\d{2}-\d{2})"', end_cell_html, flags=re.IGNORECASE)
        raw_end = _strip_cell(end_cell_html)

        end_date_str = end_date_match.group(1) if end_date_match else None
        if not end_date_str and raw_end:
            m_iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw_end)
            m_dot = re.search(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b", raw_end)
            if m_iso:
                end_date_str = m_iso.group(1)
            elif m_dot:
                try:
                    end_date_str = datetime.strptime(m_dot.group(1), "%d.%m.%Y").strftime("%Y-%m-%d")
                except ValueError:
                    end_date_str = None

        end_part = raw_end.split()[-1] if raw_end else "00:00"
        if ":" not in end_part:
            end_part = "00:00"
        if end_date_str:
            try:
                dt_end = datetime.strptime(f"{end_date_str} {end_part}", "%Y-%m-%d %H:%M")
            except ValueError:
                dt_end = None
        else:
            dt_end = None

    if not dt_start or not dt_end:
        return None

    description = _strip_cell(cells[desc_i]) if desc_i < len(cells) else ""
    description = description or "не указано"
    unavailable_services = _strip_cell(cells[services_i]) if services_i < len(cells) else ""
    unavailable_services = unavailable_services or "не указано"
    owner = _strip_cell(cells[owner_i]) if owner_i < len(cells) else ""
    notify = _strip_cell(cells[notify_i]) if notify_i < len(cells) else ""
    inform_at = None
    inform_at_str = ""
    if inform_i is not None and inform_i < len(cells):
        inform_at_str = _strip_cell(cells[inform_i]) or ""
        inform_at = _try_parse_inform_at(inform_at_str)

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
        "inform_at": inform_at,
        "inform_at_str": inform_at_str,
        "start_time": dt_start,
        "end_time": dt_end,
    }


def parse_works_table(storage: str) -> List[dict]:
    """Парсит body.storage: все непустые строки таблицы. Возвращает список dict с work_id, notify и полями для оповещения."""
    header_idx = _extract_table_header_indexes(storage)
    col_idx = dict(header_idx)
    # Если не получилось распознать колонку «Дата и время Информирования» по заголовку,
    # попробуем детект по содержимому.
    if "inform_at" not in col_idx:
        detected = _detect_inform_at_column_index(storage)
        if detected is not None:
            col_idx["inform_at"] = detected
    has_th_start_end = "start" in header_idx and "end" in header_idx
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", storage, flags=re.DOTALL | re.IGNORECASE)
    result = []
    for row_html in rows:
        if _is_row_empty(row_html):
            continue
        # Пропускаем заголовки (<th>) — мы их уже обработали
        if re.search(r"<th[^>]*>", row_html, flags=re.IGNORECASE):
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL | re.IGNORECASE)
        row = None
        if len(cells) == 10 and not has_th_start_end:
            row = _parse_row(row_html, _WIDE_10_COL)
        if row is None:
            row = _parse_row(row_html, col_idx)
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
    except asyncio.CancelledError:
        raise
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
    except asyncio.CancelledError:
        raise
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
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("[CONF_MAINT] Confluence fetch error: %s", e, exc_info=True)
        return None
    storage = (data.get("body") or {}).get("storage") or {}
    return (storage.get("value") or "") if isinstance(storage, dict) else None
