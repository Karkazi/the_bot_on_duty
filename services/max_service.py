"""
Сервис для отправки сообщений в канал MAX Messenger.
Используется для дублирования уведомлений из канала Telegram (ALARM_CHANNEL_ID) в канал MAX,
а также для архивации истории чата FA-XXXX при закрытии сбоя.
"""
import re
import logging
from typing import Optional, List, Dict, Any

import aiohttp

from config import CONFIG

logger = logging.getLogger(__name__)


def _strip_html(text: str) -> str:
    """Удаляет HTML-теги и заменяет сущности для отправки в MAX как обычный текст."""
    if not text:
        return text
    # Удаляем теги
    text = re.sub(r"<[^>]+>", "", text)
    # Распространённые сущности
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return text.strip()


class MaxService:
    """Клиент для отправки сообщений в MAX API (канал уведомлений)."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        bot_token: Optional[str] = None,
    ):
        max_cfg = CONFIG.get("MAX", {})
        self.api_url = (api_url or max_cfg.get("API_URL", "")).rstrip("/")
        self.bot_token = bot_token or max_cfg.get("BOT_TOKEN", "")
        self._enabled = bool(self.api_url and self.bot_token)
        # MAX API ожидает заголовок Authorization с самим токеном (без префикса Bearer), как в maxapi
        self._headers = {}
        if self.bot_token:
            self._headers = {
                "Authorization": self.bot_token,
                "Content-Type": "application/json",
            }

    def is_configured(self) -> bool:
        """Проверяет, заданы ли URL и токен MAX."""
        return self._enabled

    async def send_message(
        self,
        chat_id: str,
        text: str,
        strip_html: bool = True,
        format: Optional[str] = None,
    ) -> bool:
        """
        Отправляет текстовое сообщение в чат/канал MAX.

        Args:
            chat_id: ID чата или канала в MAX.
            text: Текст сообщения (при strip_html=True HTML-теги удаляются).
            strip_html: Преобразовать HTML в обычный текст (игнорируется, если format="html").
            format: Формат текста для API MAX: "html" или "markdown". Если задан, сервер рендерит разметку (ссылки, жирный и т.д.).

        Returns:
            True если отправка успешна, False в случае ошибки.
        """
        if not self._enabled:
            logger.debug("MAX не настроен, отправка пропущена")
            return False
        if not chat_id:
            logger.warning("MAX: chat_id не указан")
            return False

        use_format = (format or "").strip().lower() if format else None
        if use_format not in ("html", "markdown"):
            use_format = None
        body_text = text if use_format == "html" else (_strip_html(text) if strip_html else text)
        url = f"{self.api_url}/messages"
        params = {"chat_id": chat_id}
        payload = {"text": body_text}
        if use_format:
            payload["format"] = use_format

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    params=params,
                    json=payload,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        logger.info("Сообщение успешно отправлено в канал MAX: chat_id=%s", chat_id)
                        return True
                    err_body = await response.text()
                    logger.warning(
                        "MAX API ошибка: status=%s, url=%s, body=%s",
                        response.status,
                        url,
                        err_body[:500],
                    )
                    return False
        except Exception as e:
            logger.exception("Ошибка при отправке сообщения в MAX: %s", e)
            return False

    async def send_message_with_attachments(
        self,
        chat_id: str,
        text: str,
        attachment_tokens: Optional[List[Dict[str, Any]]] = None,
        strip_html: bool = True,
    ) -> bool:
        """
        Отправляет сообщение в чат MAX с вложениями (картинки, файлы).
        attachment_tokens: список вида [{"type": "image", "payload": {"token": "..."}},
                             {"type": "file", "payload": {"token": "...", "filename": "..."}}].
        """
        if not self._enabled or not chat_id:
            return False
        body_text = _strip_html(text) if strip_html else text
        url = f"{self.api_url}/messages"
        params = {"chat_id": chat_id}
        payload = {"text": body_text or ""}
        if attachment_tokens:
            payload["attachments"] = attachment_tokens
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    params=params,
                    json=payload,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        logger.info("Сообщение с вложениями отправлено в MAX: chat_id=%s", chat_id)
                        return True
                    err_body = await response.text()
                    logger.warning(
                        "MAX API send_message_with_attachments: status=%s, body=%s",
                        response.status,
                        err_body[:500],
                    )
                    return False
        except Exception as e:
            logger.exception("Ошибка при отправке сообщения с вложениями в MAX: %s", e)
            return False

    async def get_messages(
        self,
        chat_id: str,
        count: int = 100,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Получает историю сообщений чата (GET /messages).
        Возвращает список словарей: [{"time", "sender_id", "sender_name", "text", "mid"}, ...].
        mid — id сообщения (для удаления при очистке чата).
        """
        if not self._enabled or not chat_id:
            return None
        url = f"{self.api_url}/messages"
        params = {"chat_id": chat_id, "count": min(max(1, count), 100)}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if response.status != 200:
                        err = await response.text()
                        logger.warning("MAX get_messages: status=%s, body=%s", response.status, err[:300])
                        return None
                    data = await response.json()
        except Exception as e:
            logger.warning("MAX get_messages: %s", e)
            return None
        messages = data.get("messages") or data.get("message") or []
        if not isinstance(messages, list):
            return None
        result = []
        for m in messages:
            body = m.get("body") or m
            sender = m.get("sender") or {}
            text = (body.get("text") or "").strip()
            sender_id = sender.get("user_id") or sender.get("id")
            sender_name = sender.get("name") or sender.get("display_name") or f"user_{sender_id}" if sender_id else "?"
            ts = body.get("seq") or m.get("timestamp") or m.get("created_at")
            mid = body.get("mid") or m.get("id") or m.get("mid")
            attachments = []
            for att in (body.get("attachments") or []):
                if not isinstance(att, dict):
                    continue
                atype = (att.get("type") or "").strip().lower()
                if atype in ("contact", "inline_keyboard"):
                    continue
                payload = att.get("payload") or {}
                url_att = (payload.get("url") or "").strip() if isinstance(payload, dict) else ""
                if url_att and url_att.startswith("http"):
                    attachments.append({
                        "type": "file" if atype in ("file", "document") else ("image" if atype in ("image", "photo") else atype),
                        "url": url_att,
                        "filename": (payload.get("filename") or "").strip() or None,
                    })
            result.append({
                "time": str(ts) if ts is not None else "",
                "sender_id": sender_id,
                "sender_name": str(sender_name),
                "text": text,
                "mid": str(mid) if mid is not None else None,
                "attachments": attachments,
            })
        return result

    async def clear_chat_messages(self, chat_id: str) -> bool:
        """
        Очищает историю чата (DELETE /chats/{chatId}/messages).
        Удаляет все сообщения в чате, включая служебные (смена названия и т.п.).
        Если метод не поддерживается API (404/405), возвращает False — тогда можно
        использовать поочерёдное удаление сообщений (без служебных).
        """
        if not self._enabled or not chat_id:
            return False
        url = f"{self.api_url}/chats/{chat_id}/messages"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    url,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if response.status in (200, 204):
                        logger.info("MAX: история чата %s очищена (clear_chat_messages)", chat_id)
                        return True
                    if response.status in (404, 405, 400, 501):
                        logger.debug(
                            "MAX clear_chat_messages не поддерживается: status=%s, чат %s",
                            response.status,
                            chat_id,
                        )
                        return False
                    err = await response.text()
                    logger.warning("MAX clear_chat_messages: status=%s, body=%s", response.status, err[:200])
                    return False
        except Exception as e:
            logger.warning("MAX clear_chat_messages: %s", e)
            return False

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        """
        Удаляет сообщение в чате (DELETE /messages).
        Пробует параметры message_id и mid (разные версии API MAX).
        Возвращает True при успехе.
        """
        if not self._enabled or not chat_id or not message_id:
            return False
        url = f"{self.api_url}/messages"
        for param_name in ("mid", "message_id"):
            params = {"chat_id": chat_id, param_name: message_id}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.delete(
                        url,
                        params=params,
                        headers=self._headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        if response.status in (200, 204):
                            return True
                        if response.status in (400, 404, 422):
                            continue
                        err = await response.text()
                        logger.debug("MAX delete_message %s: status=%s body=%s", param_name, response.status, err[:200])
            except Exception as e:
                logger.warning("MAX delete_message (%s): %s", param_name, e)
        return False

    async def set_chat_title(self, chat_id: str, title: str) -> bool:
        """
        Меняет название чата (PATCH /chats/-chatId-). title 1–200 символов.
        """
        if not self._enabled or not chat_id:
            return False
        title = (title or "").strip()[:200]
        if not title:
            return False
        url = f"{self.api_url}/chats/{chat_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    url,
                    json={"title": title},
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status in (200, 204):
                        logger.info("MAX: название чата %s изменено на %r", chat_id, title[:50])
                        return True
                    err = await response.text()
                    logger.warning("MAX set_chat_title: status=%s, body=%s", response.status, err[:300])
                    return False
        except Exception as e:
            logger.warning("MAX set_chat_title: %s", e)
            return False

    async def get_chat(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает данные чата (GET /chats/-chatId-). Возвращает dict с полями link, title и др.
        """
        if not self._enabled or not chat_id:
            return None
        url = f"{self.api_url}/chats/{chat_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status != 200:
                        return None
                    return await response.json()
        except Exception as e:
            logger.warning("MAX get_chat: %s", e)
            return None

    async def delete_chat(self, chat_id: str) -> bool:
        """
        Удаляет чат (DELETE /chats/-chatId-).
        Возвращает True при успехе.
        """
        if not self._enabled or not chat_id:
            return False
        url = f"{self.api_url}/chats/{chat_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    url,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status in (200, 204):
                        logger.info("MAX: чат %s удалён", chat_id)
                        return True
                    err = await response.text()
                    logger.warning("MAX delete_chat: status=%s, body=%s", response.status, err[:300])
                    return False
        except Exception as e:
            logger.warning("MAX delete_chat: %s", e)
            return False
