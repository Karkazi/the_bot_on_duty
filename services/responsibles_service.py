import asyncio
import logging
import re
import time
from typing import Optional

from config import CONFIG
from domain.constants import PROBLEM_SERVICE_OTHER, format_alarm_service_for_display
from services.confluence_service import fetch_page_storage

logger = logging.getLogger(__name__)

_HEADER_ALIASES = {
    "service": ("сервис", "сервис/систем", "система"),
    "responsible": ("ответсвенный за устранение сбоя", "ответственный за устранение сбоя"),
    "manager": ("ответственный за сервис/систему", "ответственный за сервис", "ответственный за систему"),
    "author_name": ("имя автора сообщения",),
    "author_id": ("id автора сообщения", "id автора", "user id", "userid", "user_id"),
}

_RESPONSIBLES_CACHE: dict[str, dict] = {"by_service": {}, "expires_at": 0.0, "rows_count": 0}


def _responsibles_cfg() -> dict:
    return CONFIG.get("RESPONSIBLES", {}) or {}


def _is_enabled() -> bool:
    return bool(_responsibles_cfg().get("ENABLED", False))

def _call_master_service_enabled() -> bool:
    # Фича-флаг: если 0 — пропускаем notify_alarm_responsibles(...)
    return bool(_responsibles_cfg().get("CALL_MASTER_SERVICE_ENABLED", True))

def _notify_on_miss() -> bool:
    return bool(_responsibles_cfg().get("NOTIFY_ON_MISS", True))


def _cache_ttl_sec() -> int:
    ttl = _responsibles_cfg().get("CACHE_TTL_SEC", 900)
    try:
        value = int(ttl)
    except (TypeError, ValueError):
        return 900
    return max(value, 30)


def _page_id() -> str:
    return str(_responsibles_cfg().get("CONFLUENCE_PAGE_ID") or "").strip()


def _page_url() -> str:
    cfg = _responsibles_cfg()
    explicit_url = str(cfg.get("CONFLUENCE_PAGE_URL") or "").strip()
    if explicit_url:
        return explicit_url
    page_id = _page_id()
    login_url = str((CONFIG.get("CONFLUENCE", {}) or {}).get("LOGIN_URL") or "").strip().rstrip("/")
    if page_id and login_url:
        return f"{login_url}/pages/viewpage.action?pageId={page_id}"
    return str((CONFIG.get("CONFLUENCE", {}) or {}).get("TARGET_URL") or "").strip()


def _normalize_text(value: str) -> str:
    return " ".join((value or "").replace("\u00a0", " ").strip().lower().split())


def _normalize_service(service_name: str, service_other_spec: Optional[str] = None) -> str:
    base = (service_name or "").strip()
    if base == PROBLEM_SERVICE_OTHER:
        candidate = (service_other_spec or "").strip()
    else:
        candidate = base
    normalized = _normalize_text(candidate)
    if not normalized:
        return ""
    aliases = {
        "мах": "max",
        "max messenger": "max",
        "jira + confluence": "jira confluence",
    }
    return aliases.get(normalized, normalized)


def _strip_cell(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return " ".join(text.split()).strip()


def _extract_header_map(table_html: str) -> dict[str, int]:
    tr_match = re.search(r"<tr[^>]*>.*?<th[^>]*>.*?</th>.*?</tr>", table_html, flags=re.DOTALL | re.IGNORECASE)
    if not tr_match:
        return {}
    header_cells = re.findall(r"<th[^>]*>(.*?)</th>", tr_match.group(0), flags=re.DOTALL | re.IGNORECASE)
    if not header_cells:
        return {}
    normalized_headers = [_normalize_text(_strip_cell(cell)) for cell in header_cells]
    idx: dict[str, int] = {}
    for key, aliases in _HEADER_ALIASES.items():
        for i, header in enumerate(normalized_headers):
            if any(alias in header for alias in aliases):
                idx[key] = i
                break
    return idx


def _extract_rows_from_storage(storage: str) -> list[dict]:
    tables = re.findall(r"<table[^>]*>.*?</table>", storage or "", flags=re.DOTALL | re.IGNORECASE)
    parsed_rows: list[dict] = []
    for table_html in tables:
        header_map = _extract_header_map(table_html)
        service_i = header_map.get("service")
        responsible_i = header_map.get("responsible")
        manager_i = header_map.get("manager")
        common_author_i = header_map.get("author_name")
        common_author_id_i = header_map.get("author_id")

        if service_i is None or responsible_i is None or manager_i is None:
            continue

        for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.DOTALL | re.IGNORECASE):
            if re.search(r"<th[^>]*>", row_html, flags=re.IGNORECASE):
                continue
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.DOTALL | re.IGNORECASE)
            max_index = max(service_i, responsible_i, manager_i, common_author_i or 0, common_author_id_i or 0)
            if len(cells) <= max_index:
                continue

            service_raw = _strip_cell(cells[service_i])
            if not service_raw:
                continue
            parsed_rows.append(
                {
                    "service_raw": service_raw,
                    "service_key": _normalize_service(service_raw),
                    "responsible_raw": _strip_cell(cells[responsible_i]),
                    "manager_raw": _strip_cell(cells[manager_i]),
                    "author_name_raw": _strip_cell(cells[common_author_i]) if common_author_i is not None else "",
                    "author_id_raw": _strip_cell(cells[common_author_id_i]) if common_author_id_i is not None else "",
                }
            )
    return parsed_rows


async def _load_mapping_from_confluence() -> dict[str, dict]:
    page_id = _page_id()
    if not page_id:
        return {}
    storage = await fetch_page_storage(page_id)
    if not storage:
        return {}

    by_service: dict[str, dict] = {}
    rows = _extract_rows_from_storage(storage)
    for row in rows:
        key = row.get("service_key") or ""
        if not key:
            continue
        by_service[key] = row
    _RESPONSIBLES_CACHE["rows_count"] = len(rows)
    return by_service


async def _get_mapping() -> dict[str, dict]:
    now_ts = time.time()
    cached = _RESPONSIBLES_CACHE.get("by_service") or {}
    expires_at = float(_RESPONSIBLES_CACHE.get("expires_at") or 0.0)
    if cached and now_ts < expires_at:
        return cached

    mapping = await _load_mapping_from_confluence()
    _RESPONSIBLES_CACHE["by_service"] = mapping
    _RESPONSIBLES_CACHE["expires_at"] = now_ts + _cache_ttl_sec()
    return mapping


def _extract_author_name(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    match = re.search(r"имя автора сообщения\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if match:
        candidate = (match.group(1) or "").strip()
        # Если после имени в той же строке склеился другой атрибут, обрежем его.
        candidate = re.split(r"\s+id автора сообщения\s*:", candidate, flags=re.IGNORECASE)[0].strip()
        return candidate
    return text


def _extract_author_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    match = re.search(r"id автора сообщения\s*:\s*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return (match.group(1) or "").strip()
    plain_digits = re.search(r"\b\d{5,}\b", text)
    if plain_digits:
        return (plain_digits.group(0) or "").strip()
    return ""


def _extract_person_name_and_id(raw_value: str, fallback_name: str = "", fallback_id: str = "") -> tuple[str, str]:
    name = _extract_author_name(raw_value) or _extract_author_name(fallback_name)
    person_id = _extract_author_id(raw_value) or _extract_author_id(fallback_id)
    name = name.strip().lstrip("@")
    person_id = person_id.strip()
    return name, person_id


def _to_markdown_mention(raw_value: str, fallback_name: str = "", fallback_id: str = "") -> str:
    name, person_id = _extract_person_name_and_id(raw_value, fallback_name=fallback_name, fallback_id=fallback_id)
    if not name:
        raise ValueError("поле 'Имя автора сообщения' пустое")
    if not person_id:
        raise ValueError("поле 'ID автора сообщения' пустое")
    if not person_id.isdigit():
        raise ValueError(f"некорректный ID автора сообщения '{person_id}'")
    safe_name = name.replace("[", "\\[").replace("]", "\\]")
    return f"[{safe_name}](max://user/{person_id})"


def _format_responsibles_message(responsible_mention: str, manager_mention: str) -> str:
    return (
        "Добрый день.\n"
        f"{responsible_mention}, вы назначены ответственным за данный сбой. "
        "Просьба оперативно подключиться к решению.\n"
        f"{manager_mention}, добавляем вас для информации. "
        "В случае недоступности ответственного просьба назначить замену."
    )


def _format_fallback_message(responsible_name: str, manager_name: str) -> str:
    responsible_name = responsible_name or "ответственный за устранение сбоя"
    manager_name = manager_name or "ответственный за сервис/систему"
    return (
        "Добрый день.\n"
        f"{responsible_name}, вы назначены ответственным за данный сбой. "
        "Просьба оперативно подключиться к решению.\n"
        f"{manager_name}, добавляем вас для информации. "
        "В случае недоступности ответственного просьба назначить замену."
    )


def _format_initiator_error(service_display: str, reason: str) -> str:
    page_url = _page_url()
    page_part = page_url if page_url else "страницы Confluence"
    return (
        f"У указаного сервиса в таблице по ссылке ошибка в Ответвенных: {reason}\n"
        f"Сервис: {service_display}\n"
        f"Ссылка: {page_part}"
    )


async def notify_alarm_responsibles(
    max_service,
    fa_chat_id: str,
    initiator_user_id: int,
    service_name: str,
    service_other_spec: Optional[str] = None,
) -> None:
    """
    Отправляет сообщение с упоминанием ответственных в FA-чат по сервису.
    Если данные в Confluence некорректны/не найдены, отправляет fallback-сообщение
    в чат без @ и уведомляет инициатора (best effort).
    """
    if not _is_enabled():
        return
    if not _call_master_service_enabled():
        logger.info(
            "[RESPONSIBLES] CallMasterService отключён (CALL_MASTER_SERVICE_ENABLED=0) — пропускаем упоминания"
        )
        return
    if not fa_chat_id or not max_service or not max_service.is_configured():
        return

    service_key = _normalize_service(service_name, service_other_spec)
    service_display = format_alarm_service_for_display(service_name, service_other_spec)

    error_reason = ""
    fallback_responsible = ""
    fallback_manager = ""
    message_text = ""
    try:
        if not service_key:
            error_reason = "не удалось определить сервис для поиска ответственных"
        else:
            mapping = await _get_mapping()
            row = mapping.get(service_key)
            if not row:
                error_reason = "по сервису не найдено соответствие в таблице"
            else:
                fallback_responsible = row.get("responsible_raw") or ""
                fallback_manager = row.get("manager_raw") or ""
                common_author_name = row.get("author_name_raw") or ""
                common_author_id = row.get("author_id_raw") or ""
                responsible_mention = _to_markdown_mention(
                    fallback_responsible,
                    fallback_name=common_author_name,
                    fallback_id=common_author_id,
                )
                manager_mention = _to_markdown_mention(
                    fallback_manager,
                    fallback_name=common_author_name,
                    fallback_id=common_author_id,
                )
                message_text = _format_responsibles_message(responsible_mention, manager_mention)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        error_reason = str(e)

    if not message_text:
        message_text = _format_fallback_message(fallback_responsible, fallback_manager)

    send_format = "markdown" if not error_reason else None
    sent = await max_service.send_message(
        fa_chat_id,
        message_text,
        strip_html=(send_format is None),
        format=send_format,
    )
    if sent:
        if error_reason:
            logger.warning(
                "[RESPONSIBLES] Fallback для сервиса '%s': %s",
                service_display,
                error_reason,
            )
        else:
            logger.info("[RESPONSIBLES] Mention отправлен для сервиса '%s'", service_display)
    else:
        logger.warning("[RESPONSIBLES] Не удалось отправить сообщение в FA-чат %s", fa_chat_id)

    if error_reason and _notify_on_miss():
        try:
            user_text = _format_initiator_error(service_display, error_reason)
            await max_service.send_message_to_user(initiator_user_id, user_text, strip_html=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[RESPONSIBLES] Не удалось уведомить инициатора %s: %s", initiator_user_id, e)
