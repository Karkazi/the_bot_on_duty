"""
Загрузка и скачивание вложений MAX (картинки, файлы) для моста TG↔MAX и архивации в Jira.
Идеи и формат API взяты из bot_rubik (adapters/max/main_max.py).
"""
import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from aiohttp import FormData

from config import CONFIG

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE_MB = 20
MAX_ATTACHMENTS_DOWNLOAD_RETRIES = 3


def _max_headers() -> dict:
    token = (CONFIG.get("MAX", {}) or {}).get("BOT_TOKEN", "").strip()
    return {
        "Authorization": token,
        "Content-Type": "application/json",
    }


def _max_base_url() -> str:
    return ((CONFIG.get("MAX", {}) or {}).get("API_URL") or "https://platform-api.max.ru").rstrip("/")


def _is_configured() -> bool:
    cfg = CONFIG.get("MAX", {}) or {}
    return bool(cfg.get("API_URL") and cfg.get("BOT_TOKEN"))


def extract_attachments_from_max_message(body_or_message: Any) -> List[Dict[str, Any]]:
    """
    Извлекает вложения из сообщения MAX (body.attachments или message.body).
    Возвращает список {"type": "image"|"file"|"video"|"audio", "url": str, "filename": str|None}.
    Для скачивания нужен url; если только token — url может отсутствовать в ответе API.
    """
    out = []
    if body_or_message is None:
        return out
    body = body_or_message
    if hasattr(body_or_message, "body"):
        body = getattr(body_or_message, "body", None) or body_or_message
    attachments = []
    if hasattr(body, "attachments"):
        attachments = getattr(body, "attachments", None) or []
    if not attachments and isinstance(body, dict):
        attachments = body.get("attachments") or []
    for att in attachments:
        if att is None:
            continue
        atype = getattr(att, "type", None) if not isinstance(att, dict) else att.get("type")
        atype = (atype or "").strip().lower()
        if atype in ("contact", "inline_keyboard"):
            continue
        if atype not in ("image", "photo", "file", "document", "video", "audio"):
            continue
        payload = getattr(att, "payload", None) if not isinstance(att, dict) else att.get("payload")
        url = ""
        filename = ""
        if isinstance(payload, dict):
            url = (payload.get("url") or "").strip()
            filename = (payload.get("filename") or "").strip()
        elif hasattr(att, "url"):
            url = (getattr(att, "url", None) or "").strip()
        if isinstance(att, dict):
            url = url or (att.get("url") or ((att.get("payload") or {}).get("url") if isinstance(att.get("payload"), dict) else ""))
            if not filename and isinstance(att.get("payload"), dict):
                filename = (att.get("payload", {}).get("filename") or "").strip()
        kind = "file" if atype in ("file", "document") else ("image" if atype in ("image", "photo") else atype)
        if url and url.startswith("http"):
            out.append({"type": kind, "url": url, "filename": filename or None})
    return out


async def download_attachment_max(url: str, att_type: str = "", filename: str = "") -> Optional[Tuple[bytes, str]]:
    """
    Скачивает вложение по URL (CDN MAX). Возвращает (content, filename) или None.
    """
    if not url or not url.strip().startswith("http"):
        return None
    ext_by_type = {"image": ".jpg", "photo": ".jpg", "video": ".mp4", "audio": ".m4a", "file": ""}
    default_ext = ext_by_type.get(att_type, ".bin")
    for attempt in range(MAX_ATTACHMENTS_DOWNLOAD_RETRIES):
        try:
            timeout = aiohttp.ClientTimeout(total=30, sock_connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning("MAX: GET вложение %s вернул %s (попытка %s)", url[:80], resp.status, attempt + 1)
                        if attempt < MAX_ATTACHMENTS_DOWNLOAD_RETRIES - 1:
                            await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    content = await resp.read()
                    if not content:
                        return None
                    name = (resp.headers.get("Content-Disposition") or "").split("filename=")[-1].strip(' "\n')
                    if not name or "filename=" in name or len(name) > 200:
                        name = filename or f"attachment_{url.split('/')[-1].split('?')[0][:20] or 'file'}{default_ext}"
                    logger.debug("MAX: вложение скачано, размер %s", len(content))
                    return (content, name)
        except Exception as e:
            logger.warning("MAX: ошибка скачивания вложения (попытка %s): %s", attempt + 1, e)
            if attempt < MAX_ATTACHMENTS_DOWNLOAD_RETRIES - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
    return None


def _mime_for_path(path: str) -> str:
    p = (path or "").lower()
    if p.endswith(".png"):
        return "image/png"
    if p.endswith(".gif"):
        return "image/gif"
    if p.endswith(".webp"):
        return "image/webp"
    if p.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if p.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return "application/octet-stream"


async def upload_image_max(image_path: str) -> Optional[str]:
    """
    Загружает изображение в MAX (POST /uploads). Возвращает token для вложения в сообщение или None.
    """
    if not _is_configured():
        return None
    path = Path(image_path)
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        logger.warning("MAX: файл %s превышает %s МБ", path.name, MAX_UPLOAD_SIZE_MB)
        return None
    try:
        raw = path.read_bytes()
    except Exception as e:
        logger.warning("MAX: не удалось прочитать файл %s: %s", image_path, e)
        return None
    file_name = path.name or "image.jpg"
    mime_type = _mime_for_path(image_path)
    if not mime_type.startswith("image/"):
        mime_type = "image/jpeg"
    base = _max_base_url()
    url = f"{base}/uploads"
    # Некоторые инстансы MAX используют botapi.max.ru для uploads
    upload_base = base
    if "platform-api" in base:
        upload_base = "https://botapi.max.ru"
        url = f"{upload_base}/uploads"
    headers = _max_headers()
    body = {"type": "image", "file_name": file_name, "file_size": len(raw), "mime_type": mime_type}
    resp = None
    last_status = None
    last_body = ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                params={"type": "image"},
                json=body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                last_status = r.status
                last_body = (await r.text())[:500]
                if r.status == 200:
                    try:
                        import json
                        resp = json.loads(last_body) if last_body.strip() else {}
                    except Exception:
                        resp = {}
                elif r.status == 400:
                    logger.debug("MAX POST /uploads 400: %s", last_body[:300])
    except Exception as e:
        logger.debug("MAX upload request: %s", e)
    if not resp or not isinstance(resp, dict):
        logger.warning(
            "MAX upload_image_max: первый запрос к %s вернул status=%s, body=%s",
            url, last_status, last_body[:300] if last_body else "(пусто)",
        )
        return None
    token = resp.get("token") or resp.get("file_token") or resp.get("photo_id")
    upload_url = resp.get("url") or resp.get("upload_url")
    if upload_url and not token:
        async def _parse_token(up_resp):
            ct = up_resp.content_type or ""
            text = await up_resp.text()
            for h in ("X-Photo-Id", "X-Photo-Token", "X-File-Token", "X-Token"):
                v = up_resp.headers.get(h)
                if v and str(v).strip():
                    return str(v).strip()
            if "application/json" in ct and text.strip():
                try:
                    import json
                    data = json.loads(text)
                except Exception:
                    data = {}
                if isinstance(data, dict):
                    t = data.get("token") or data.get("file_token") or data.get("photo_id") or data.get("file_id") or data.get("id")
                    if t is not None:
                        return str(t)
                    photos = data.get("photos")
                    if isinstance(photos, dict) and photos:
                        first = next(iter(photos.values()), None)
                        if isinstance(first, dict):
                            t = first.get("token") or first.get("file_token") or first.get("photo_id")
                            if t is not None:
                                return str(t)
            return None
        token = None
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(upload_url, data=raw, headers={"Content-Type": mime_type}, timeout=aiohttp.ClientTimeout(total=30)) as up_resp:
                        if up_resp.status < 400:
                            token = await _parse_token(up_resp)
            except Exception as e:
                logger.warning("MAX upload file POST, попытка %s: %s", attempt + 1, e)
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
            if token:
                break
        if not token:
            try:
                fd = FormData()
                fd.add_field("file", raw, filename=file_name, content_type=mime_type)
                async with aiohttp.ClientSession() as session:
                    async with session.post(upload_url, data=fd, timeout=aiohttp.ClientTimeout(total=30)) as up_resp:
                        if up_resp.status < 400:
                            token = await _parse_token(up_resp)
                        else:
                            err_body = (await up_resp.text())[:300]
                            logger.warning(
                                "MAX upload_image_max: POST по upload_url вернул status=%s, body=%s",
                                up_resp.status, err_body,
                            )
            except Exception as e:
                logger.debug("MAX upload multipart: %s", e)
    if not token:
        logger.warning(
            "MAX upload_image_max: не удалось получить token (первый resp keys=%s, upload_url=%s)",
            list(resp.keys()) if isinstance(resp, dict) else None, bool(upload_url),
        )
    return str(token).strip() if token else None


async def upload_file_max(file_path: str, mime_type: Optional[str] = None) -> Optional[str]:
    """
    Загружает файл (документ) в MAX. Возвращает token для вложения в сообщение или None.
    """
    if not _is_configured():
        return None
    path = Path(file_path)
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        logger.warning("MAX: файл %s превышает %s МБ", path.name, MAX_UPLOAD_SIZE_MB)
        return None
    try:
        raw = path.read_bytes()
    except Exception as e:
        logger.warning("MAX: не удалось прочитать файл %s: %s", file_path, e)
        return None
    file_name = path.name or "file"
    mime = mime_type or _mime_for_path(file_path)
    base = _max_base_url()
    if "platform-api" in base:
        base = "https://botapi.max.ru"
    url = f"{base}/uploads"
    headers = _max_headers()
    body = {"type": "file", "file_name": file_name, "file_size": len(raw), "mime_type": mime}
    resp = None
    last_status = None
    last_body = ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, params={"type": "file"}, json=body, timeout=aiohttp.ClientTimeout(total=15)) as r:
                last_status = r.status
                last_body = (await r.text())[:500]
                if r.status == 200:
                    try:
                        import json
                        resp = json.loads(last_body) if last_body.strip() else {}
                    except Exception:
                        resp = {}
    except Exception as e:
        logger.debug("MAX upload file request: %s", e)
    if not resp or not isinstance(resp, dict):
        logger.warning(
            "MAX upload_file_max: первый запрос к %s вернул status=%s, body=%s",
            url, last_status, last_body[:300] if last_body else "(пусто)",
        )
        return None
    token = resp.get("token") or resp.get("file_token") or resp.get("document_id")
    upload_url = resp.get("url") or resp.get("upload_url")
    if upload_url and not token:
        async def _parse_token(up_resp):
            text = await up_resp.text()
            for h in ("X-File-Token", "X-Document-Id", "X-Token"):
                v = up_resp.headers.get(h)
                if v and str(v).strip():
                    return str(v).strip()
            if up_resp.content_type and "json" in (up_resp.content_type or ""):
                try:
                    import json
                    data = json.loads(text)
                    if isinstance(data, dict):
                        return data.get("token") or data.get("file_token") or data.get("document_id") or data.get("file_id") or data.get("id")
                except Exception:
                    pass
            return None
        token = None
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(upload_url, data=raw, headers={"Content-Type": mime}, timeout=aiohttp.ClientTimeout(total=30)) as up_resp:
                        if up_resp.status < 400:
                            token = await _parse_token(up_resp)
            except Exception as e:
                logger.warning("MAX upload file POST, попытка %s: %s", attempt + 1, e)
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
            if token:
                break
    return str(token).strip() if token else None


def build_max_attachments_for_message(image_tokens: List[str], file_tokens: List[Tuple[str, Optional[str]]]) -> List[Dict[str, Any]]:
    """
    Формирует список вложений для body.attachments при отправке сообщения в MAX.
    image_tokens — список токенов картинок; file_tokens — список (token, filename).
    """
    out = []
    for t in image_tokens:
        if t:
            out.append({"type": "image", "payload": {"token": t}})
    for t, name in file_tokens:
        if t:
            payload = {"token": t}
            if name:
                payload["filename"] = name
            out.append({"type": "file", "payload": payload})
    return out
