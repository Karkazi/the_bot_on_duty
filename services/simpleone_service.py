"""
Сервис для работы с SimpleOne API.
Публикует сообщения на портал Петлокал.
Поддерживает автоматическое обновление токена по логину/паролю (срок жизни токена ~120 мин).
"""
import asyncio
import logging
import json
from typing import Optional, Dict, Any
import aiohttp

from config import CONFIG

logger = logging.getLogger(__name__)


class SimpleOneService:
    """Сервис для работы с SimpleOne API"""
    
    def __init__(self):
        """Инициализация сервиса"""
        self.base_url = CONFIG.get("SIMPLEONE", {}).get("BASE_URL", "")
        self.group_id = CONFIG.get("SIMPLEONE", {}).get("GROUP_ID", "")
        self.comments_api_scope = CONFIG.get("SIMPLEONE", {}).get("COMMENTS_API_SCOPE", "")
        self.comments_api_path = CONFIG.get("SIMPLEONE", {}).get("COMMENTS_API_PATH", "")
        self.session: Optional[aiohttp.ClientSession] = None
    
    def _get_token(self) -> str:
        """Возвращает текущий токен из конфига (обновляется при автоматическом перевыпуске)."""
        return CONFIG.get("SIMPLEONE", {}).get("TOKEN", "")
    
    async def __aenter__(self):
        """Асинхронный контекстный менеджер - вход"""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный контекстный менеджер - выход"""
        if self.session:
            await self.session.close()
    
    def _is_configured(self) -> bool:
        """Проверяет, настроен ли сервис"""
        return bool(self.base_url and self._get_token() and self.group_id)
    
    async def _refresh_token_if_configured(self, save_to_env: bool = True) -> bool:
        """
        Если в конфиге заданы SIMPLEONE_USERNAME и SIMPLEONE_PASSWORD, получает новый токен
        по API и обновляет CONFIG и при необходимости .env. Возвращает True, если токен обновлён.
        """
        username = CONFIG.get("SIMPLEONE", {}).get("USERNAME")
        password = CONFIG.get("SIMPLEONE", {}).get("PASSWORD")
        if not username or not password:
            return False
        try:
            from utils.simpleone_token import get_new_token, update_env_token
            new_token = await asyncio.to_thread(
                get_new_token, self.base_url, username, password
            )
            if new_token:
                CONFIG["SIMPLEONE"]["TOKEN"] = new_token
                import os
                os.environ["SIMPLEONE_TOKEN"] = new_token
                if save_to_env:
                    update_env_token(new_token)
                logger.info("Токен SimpleOne успешно обновлён (автоматически)")
                return True
        except Exception as e:
            logger.warning("Не удалось обновить токен SimpleOne: %s", e, exc_info=True)
        return False
    
    @staticmethod
    def _get_error_message(status: int, error_data: Any = None, response_text: str = "") -> str:
        """
        Определяет понятное сообщение об ошибке на основе HTTP статуса.
        
        Args:
            status: HTTP статус код
            error_data: Данные об ошибке из JSON ответа
            response_text: Текст ответа (если JSON не распарсился)
        
        Returns:
            Понятное сообщение об ошибке
        """
        if status == 401:
            return "Токен SimpleOne устарел. Токены действительны 2 часа. Обновите токен в настройках бота."
        elif status == 403:
            return "Нет доступа к SimpleOne API. Проверьте права токена."
        elif status == 404:
            return "Ресурс не найден в SimpleOne."
        elif status == 400:
            return "Неверный запрос к SimpleOne API."
        elif status >= 500:
            return "Ошибка сервера SimpleOne. Попробуйте позже."
        else:
            # Пытаемся извлечь сообщение из error_data
            if error_data:
                if isinstance(error_data, dict):
                    errors = error_data.get("errors", [])
                    if errors and isinstance(errors, list) and len(errors) > 0:
                        error_msg = errors[0].get("message", "")
                        if error_msg:
                            return error_msg
                    error_msg = error_data.get("error", "")
                    if error_msg:
                        return error_msg
            if response_text:
                return f"Ошибка SimpleOne: {response_text[:200]}"
            return "Неизвестная ошибка SimpleOne API"
    
    async def create_portal_post(
        self,
        content: str,
        title: Optional[str] = None,
        state: str = "published",
        active: bool = True,
        post_type: str = "post"
    ) -> Dict[str, Any]:
        """
        Создает пост на портале Петлокал.
        
        Args:
            content: HTML содержимое поста
            title: Заголовок поста (опционально)
            state: Состояние публикации (по умолчанию "published")
            active: Активен ли пост (по умолчанию True)
            post_type: Тип поста (по умолчанию "post" - для отображения на портале petlocal)
        
        Returns:
            dict: Результат создания поста
        """
        if not self._is_configured():
            logger.warning("SimpleOne не настроен. Пропускаем публикацию.")
            return {
                "success": False,
                "error": "SimpleOne не настроен в конфигурации"
            }
        
        url = f"{self.base_url}/rest/v1/table/c_portal_news"
        
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "content": content,
            "state": state,
            "type": post_type,
            "group_id": self.group_id
        }
        
        if title:
            payload["title"] = title
        if active is not None:
            payload["active"] = active
        
        logger.info(f"Отправка запроса на создание поста в SimpleOne: {url}")
        logger.debug(f"Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        
        try:
            async with self.session.post(url, json=payload, headers=headers) as response:
                response_text = await response.text()
                
                logger.info(f"Статус ответа SimpleOne: {response.status}")
                logger.debug(f"Полный ответ API: {response_text[:1000]}")
                
                if response.status in (200, 201):
                    try:
                        response_data = await response.json()
                        logger.info(f"Успешно создан пост в SimpleOne")
                        
                        # Извлекаем информацию о созданном посте
                        created_post = None
                        if isinstance(response_data, dict):
                            if "data" in response_data:
                                created_post = response_data["data"]
                                if isinstance(created_post, list) and created_post:
                                    created_post = created_post[0]
                            elif "result" in response_data:
                                created_post = response_data["result"]
                            else:
                                created_post = response_data
                        
                        return {
                            "success": True,
                            "data": response_data,
                            "created_post": created_post,
                            "status": response.status
                        }
                    except Exception as e:
                        logger.warning("Не удалось распарсить JSON ответ: %s, текст: %s", e, response_text[:500], exc_info=True)
                        return {
                            "success": True,
                            "data": {"raw_response": response_text},
                            "status": response.status
                        }
                else:
                    # При 401 пробуем один раз обновить токен по логину/паролю и повторить запрос
                    if response.status == 401 and await self._refresh_token_if_configured():
                        headers = {
                            "Authorization": f"Bearer {self._get_token()}",
                            "Content-Type": "application/json"
                        }
                        async with self.session.post(url, json=payload, headers=headers) as response2:
                            response_text2 = await response2.text()
                            if response2.status in (200, 201):
                                try:
                                    response_data = await response2.json()
                                    created_post = None
                                    if isinstance(response_data, dict):
                                        if "data" in response_data:
                                            created_post = response_data["data"]
                                            if isinstance(created_post, list) and created_post:
                                                created_post = created_post[0]
                                        elif "result" in response_data:
                                            created_post = response_data["result"]
                                        else:
                                            created_post = response_data
                                    return {
                                        "success": True,
                                        "data": response_data,
                                        "created_post": created_post,
                                        "status": response2.status
                                    }
                                except Exception as parse_err:
                                    logger.warning("Повторный запрос SimpleOne: не удалось распарсить JSON: %s", parse_err)
                                    return {
                                        "success": True,
                                        "data": {"raw_response": response_text2},
                                        "status": response2.status
                                    }
                    try:
                        error_data = json.loads(response_text) if response_text else None
                    except Exception as parse_err:
                        logger.debug("Не удалось распарсить тело ошибки: %s", parse_err)
                        error_data = None
                    error_msg = self._get_error_message(response.status, error_data, response_text)
                    logger.error(f"Ошибка SimpleOne API (HTTP {response.status}): {error_msg}")
                    if response.status == 401:
                        logger.warning("Токен SimpleOne устарел! Требуется обновление токена в настройках.")
                    return {
                        "success": False,
                        "error": error_msg,
                        "status": response.status,
                        "data": error_data,
                        "is_token_expired": response.status == 401
                    }
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка сети при публикации в SimpleOne: {e}")
            return {
                "success": False,
                "error": f"Ошибка сети: {e}"
            }
        except Exception as e:
            logger.error(f"Неожиданная ошибка при публикации в SimpleOne: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Неожиданная ошибка: {e}"
            }

    async def get_latest_portal_posts(self, limit: int = 20) -> Dict[str, Any]:
        """
        Получает последние посты из c_portal_news и фильтрует по group_id на клиенте.
        """
        if not self._is_configured():
            return {"success": False, "error": "SimpleOne не настроен в конфигурации"}

        url = f"{self.base_url}/rest/v1/table/c_portal_news"
        headers = {"Authorization": f"Bearer {self._get_token()}"}
        params = {"sysparm_limit": max(int(limit), 1)}

        try:
            async with self.session.get(url, headers=headers, params=params) as response:
                text = await response.text()
                if response.status != 200:
                    error_msg = self._get_error_message(response.status, None, text)
                    if response.status == 401:
                        logger.warning("Токен SimpleOne устарел! Требуется обновление токена в настройках.")
                    return {
                        "success": False,
                        "status": response.status,
                        "error": error_msg,
                        "is_token_expired": response.status == 401
                    }

                data = await response.json()
                rows = data.get("data") or data.get("result") or []
                if not isinstance(rows, list):
                    rows = []

                filtered = []
                for row in rows:
                    gid = row.get("group_id")
                    gid_val = gid.get("value") if isinstance(gid, dict) else gid
                    if str(gid_val) == str(self.group_id):
                        filtered.append(row)

                return {"success": True, "status": response.status, "data": filtered}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def format_alarm_closed_for_petlocal(self, alarm_id: str, issue: str, closed_at: str) -> str:
        """Форматирует пост о закрытии сбоя для публикации на Петлокале (HTML)."""
        html = "<h2>✅ Сбой устранён</h2>\n"
        html += f"<p><strong>ID:</strong> {self._escape_html(alarm_id)}</p>\n"
        html += f"<p><strong>Проблема:</strong> {self._escape_html(issue)}</p>\n"
        html += f"<p><strong>Время закрытия:</strong> {self._escape_html(closed_at)}</p>"
        return html

    def format_maintenance_closed_for_petlocal(self, work_id: str, description: str, closed_at: str) -> str:
        """Форматирует пост о завершении работ для публикации на Петлокале (HTML)."""
        html = "<h2>✅ Работы завершены</h2>\n"
        html += f"<p><strong>ID:</strong> {self._escape_html(work_id)}</p>\n"
        html += f"<p><strong>Описание:</strong> {self._escape_html(description)}</p>\n"
        html += f"<p><strong>Время завершения:</strong> {self._escape_html(closed_at)}</p>"
        return html

    def format_alarm_for_petlocal(
        self,
        issue: str,
        service: str,
        fix_time: str,
        description: Optional[str] = None,
        jira_url: Optional[str] = None,
        alarm_id: Optional[str] = None
    ) -> str:
        """
        Форматирует сообщение об аварии для публикации на Петлокале (HTML).
        
        Args:
            issue: Краткое описание проблемы
            service: Затронутый сервис
            fix_time: Время исправления
            description: Полное описание (если отличается от issue)
            jira_url: Ссылка на задачу в Jira (если есть)
            alarm_id: ID аварии
        
        Returns:
            HTML строка для публикации
        """
        full_description = description or issue
        
        html = f"<h2>🚨 Технический сбой</h2>\n"
        html += f"<p><strong>Проблема:</strong> {self._escape_html(issue)}</p>\n"
        html += f"<p><strong>Сервис:</strong> {self._escape_html(service)}</p>\n"
        html += f"<p><strong>Исправим до:</strong> {self._escape_html(fix_time)}</p>\n"
        html += f"<p><strong>Описание:</strong></p>\n"
        html += f"<p>{self._escape_html(full_description)}</p>\n"
        html += f"<p><em>Мы уже работаем над устранением сбоя. Спасибо за ваше терпение и понимание!</em></p>"
        
        return html
    
    def format_maintenance_for_petlocal(
        self,
        description: str,
        start_time: str,
        end_time: str,
        unavailable_services: str
    ) -> str:
        """
        Форматирует сообщение о регламентных работах для публикации на Петлокале (HTML).
        
        Args:
            description: Описание работ
            start_time: Время начала
            end_time: Время окончания
            unavailable_services: Недоступные сервисы
        
        Returns:
            HTML строка для публикации
        """
        html = f"<h2>🔧 Плановые технические работы</h2>\n"
        html += f"<p><strong>Описание:</strong> {self._escape_html(description)}</p>\n"
        html += f"<p><strong>Начало:</strong> {self._escape_html(start_time)}</p>\n"
        html += f"<p><strong>Конец:</strong> {self._escape_html(end_time)}</p>\n"
        html += f"<p><strong>Недоступно:</strong> {self._escape_html(unavailable_services)}</p>\n"
        html += f"<p><em>Спасибо за понимание! Эти изменения – важный шаг к тому, чтобы сервис стал ещё удобнее и надёжнее для вас 💙</em></p>\n"
        html += f"<p><em>Если возникнут вопросы – наша поддержка всегда на связи</em></p>\n"
        html += f"<p><em>С заботой, Ваша команда Петрович-ТЕХ</em></p>"
        
        return html
    
    def format_regular_message_for_petlocal(
        self,
        message_text: str,
        image_base64: Optional[str] = None,
        image_media_type: str = "image/jpeg",
    ) -> str:
        """
        Форматирует обычное сообщение для публикации на Петлокале (HTML).
        
        Args:
            message_text: Текст сообщения
            image_base64: Опционально — изображение в base64 для вставки в пост
            image_media_type: MIME-тип изображения (по умолчанию image/jpeg)
        
        Returns:
            HTML строка для публикации
        """
        html = f"<h2>💬 Сообщение от администратора</h2>\n"
        html += f"<p>{self._escape_html(message_text)}</p>\n"
        if image_base64:
            html += f'<p><img src="data:{image_media_type};base64,{image_base64}" alt="Изображение" style="max-width:100%;height:auto;" /></p>\n'
        return html
    
    @staticmethod
    def _escape_html(text: str) -> str:
        """
        Экранирует HTML символы для безопасного отображения.
        
        Args:
            text: Текст для экранирования
        
        Returns:
            Экранированный текст
        """
        if not text:
            return ""
        return (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#x27;")
        )
