# config.py

import os
import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger(__name__)

# Загружаем переменные окружения из .env файла
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logger.info(f"✅ Загружен .env файл: {env_path}")
else:
    # Пробуем загрузить из корня проекта
    root_env = Path(__file__).parent.parent / ".env"
    if root_env.exists():
        load_dotenv(root_env)
        logger.info(f"✅ Загружен .env файл: {root_env}")
    else:
        # Пробуем загрузить из текущей директории
        load_dotenv()
        logger.warning("⚠️ .env файл не найден, используются переменные окружения системы")

# Списки опций
PROBLEM_LEVELS = [
    "Замедление работы сервиса",
    "Полная недоступность сервиса",
    "Частичная недоступность сервиса",
    "Проблемы в работе сервиса",
    "Потенциальная недоступность сервиса"
]

PROBLEM_SERVICES = [
    "Naumen", "Электронная почта", "УТЦ", "УТ Юнион", "1С УТ СПБ", "1С УТ СЗФО",
    "1С УТ МСК", "1С ЦФС", "УТ СПБ+УТ СЗФО+ УТ МСК", "LMS", "Проблема с обменами",
    "Сеть и интернет 1 подразделения", "Удалённый рабочий стол RDP (trm)",
    "Удалённый рабочий стол RDP для КЦ (retrm)", "VPN офисный", "VPN ДО КЦ",
    "Стационарная телефония", "Мобильная телефония", "Сетевое хранилище (Диск Х)",
    "Сайт Petrovich.ru", "Чат на сайте", "Jira", "Confluence", "Petlocal.ru",
    "Электроэнергия", "Телеопти/Май тайм", "Сервис оплаты", "Jira + Confluence",
    "b2b.stdp.ru", "Skype for business(Lync)", "DocsVision (DV)", "УТ СПБ",
    "ЗУП", "HR-Link", "WMS", "Мобильное приложение", "Другое"
]

INFLUENCE_OPTIONS = ["Клиенты", "Бизнес-функция", "Сотрудники"]


def _parse_max_fa_chat_ids() -> list:
    """Список ID чатов MAX для обсуждения сбоев (1–4). Порядок: первый чат, второй, третий, четвёртый."""
    ids = []
    # Первый чат: MAX_ALARM_FA_CHAT_1_ID или устаревший MAX_ALARM_FA_CHAT_ID
    id1 = (os.getenv("MAX_ALARM_FA_CHAT_1_ID") or os.getenv("MAX_ALARM_FA_CHAT_ID") or "").strip()
    if id1:
        ids.append(id1)
    for key in ("MAX_ALARM_FA_CHAT_2_ID", "MAX_ALARM_FA_CHAT_3_ID", "MAX_ALARM_FA_CHAT_4_ID"):
        val = (os.getenv(key) or "").strip()
        if val:
            ids.append(val)
    return ids


def get_next_max_fa_chat_id(active_alarms_count: int) -> Optional[str]:
    """
    Возвращает ID чата MAX для нового сбоя по количеству уже активных сбоёв.
    При 1 активном — первый чат, при 2 — второй, при 3 — третий, при 4+ — четвёртый.
    """
    chat_ids = CONFIG.get("MAX", {}).get("ALARM_FA_CHAT_IDS") or []
    if not chat_ids:
        return None
    index = min(active_alarms_count - 1, len(chat_ids) - 1)
    if index < 0:
        index = 0
    return chat_ids[index]


def _parse_max_bot_user_id() -> Optional[int]:
    """Парсит MAX_BOT_USER_ID из .env (user_id бота в MAX для модерации ALARM_MAIN)."""
    s = (os.getenv("MAX_BOT_USER_ID", "") or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        logger.warning("⚠️ Некорректный MAX_BOT_USER_ID: '%s'", s)
        return None


def _parse_max_admin_ids() -> list:
    """Парсит MAX_ADMIN_IDS из .env (список user_id в MAX для управления ботом)."""
    s = os.getenv("MAX_ADMIN_IDS", "")
    ids = []
    for part in (s or "").split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                logger.warning(f"⚠️ Некорректный MAX_ADMIN_ID пропущен: '{part}'")
    return ids


def load_config() -> Dict[str, Any]:
    """
    Загружает конфигурацию из переменных окружения (.env файл).
    """
    logger.info("⚙️ Загружаю конфигурацию из .env")

    # Парсим ADMIN_IDS и SUPERADMIN_IDS из строки через запятую
    # Добавлена обработка ошибок для некорректных значений
    admin_ids_str = os.getenv("ADMIN_IDS", "")
    admin_ids = []
    if admin_ids_str:
        for id_str in admin_ids_str.split(","):
            id_str = id_str.strip()
            if id_str:
                try:
                    admin_ids.append(int(id_str))
                except ValueError:
                    logger.warning(f"⚠️ Некорректный ADMIN_ID пропущен: '{id_str}'")

    superadmin_ids_str = os.getenv("SUPERADMIN_IDS", "")
    superadmin_ids = []
    if superadmin_ids_str:
        for id_str in superadmin_ids_str.split(","):
            id_str = id_str.strip()
            if id_str:
                try:
                    superadmin_ids.append(int(id_str))
                except ValueError:
                    logger.warning(f"⚠️ Некорректный SUPERADMIN_ID пропущен: '{id_str}'")

    # Безопасное получение и обработка URL (защита от None)
    confluence_login_url = os.getenv("CONFLUENCE_LOGIN_URL", "https://confluence.example.com/login.action")
    confluence_target_url = os.getenv("CONFLUENCE_TARGET_URL", "https://confluence.example.com/pages/viewpage.action?pageId=0")
    jira_login_url = os.getenv("JIRA_LOGIN_URL", "https://jira.example.com/login.jsp")
    
    config = {
        "CONFLUENCE": {
            "LOGIN_URL": confluence_login_url.strip() if confluence_login_url else "",
            "TARGET_URL": confluence_target_url.strip() if confluence_target_url else "",
            "USERNAME": os.getenv("CONFLUENCE_USERNAME", ""),
            "PASSWORD": os.getenv("CONFLUENCE_PASSWORD", "")
        },
        "TELEGRAM": {
            "TOKEN": os.getenv("TELEGRAM_TOKEN", ""),
            "ALARM_CHANNEL_ID": os.getenv("ALARM_CHANNEL_ID", ""),
            "SCM_CHANNEL_ID": os.getenv("SCM_CHANNEL_ID", ""),
            "ADMIN_IDS": admin_ids,
            "SUPERADMIN_IDS": superadmin_ids,
            # icon_custom_emoji_id для иконок тем SCM (editForumTopic)
            "TOPIC_ICON_DONE_ID": (os.getenv("TELEGRAM_TOPIC_ICON_DONE_ID", "").strip() or None),
            "TOPIC_ICON_FIRE_ID": (os.getenv("TELEGRAM_TOPIC_ICON_FIRE_ID", "").strip() or None),
        },
        "JIRA": {
            "LOGIN_URL": jira_login_url.strip() if jira_login_url else "",
            "USERNAME": os.getenv("JIRA_USERNAME", ""),
            "PASSWORD": os.getenv("JIRA_PASSWORD", ""),
            "TOKEN": os.getenv("JIRA_TOKEN", "")
        },
        "SIMPLEONE": {
            "BASE_URL": os.getenv("SIMPLEONE_BASE_URL", "https://simpleone.example.com"),
            "TOKEN": os.getenv("SIMPLEONE_TOKEN", ""),
            "USERNAME": os.getenv("SIMPLEONE_USERNAME", "").strip() or None,
            "PASSWORD": os.getenv("SIMPLEONE_PASSWORD", "").strip() or None,
            "GROUP_ID": os.getenv("SIMPLEONE_GROUP_ID", ""),
            # Scripted REST API для работы с комментариями (опционально)
            # Если не указано, используется старый метод через прямые запросы к таблицам
            "COMMENTS_API_SCOPE": os.getenv("SIMPLEONE_COMMENTS_API_SCOPE", ""),  # Например: "sn_customerservice"
            # Или можно указать полный путь к API:
            "COMMENTS_API_PATH": os.getenv("SIMPLEONE_COMMENTS_API_PATH", ""),  # Например: "/api/x_sn_customerservice/petlocal_comments/add_comment"
            # Прокси для запросов к SimpleOne (опционально): http://host:port или http://user:pass@host:port
            "PROXY_URL": os.getenv("SIMPLEONE_PROXY_URL", "").strip() or None,
        },
        # MAX Messenger (опционально): дублирование уведомлений в канал MAX и управление ботом из MAX
        # API_URL по умолчанию как в maxapi (platform-api.max.ru); можно переопределить через .env
        "MAX": {
            "API_URL": (os.getenv("MAX_API_URL") or "https://platform-api.max.ru").rstrip("/"),
            "BOT_TOKEN": os.getenv("MAX_BOT_TOKEN", ""),
            "ALARM_CHANNEL_ID": os.getenv("MAX_ALARM_CHANNEL_ID", "").strip() or None,
            # Чат ALARM_MAIN: сюда бот шлёт уведомления о новых сбоях (FA-XXXX); только посты бота и админов
            "ALARM_MAIN_CHAT_ID": os.getenv("MAX_ALARM_MAIN_CHAT_ID", "").strip() or None,
            # Чаты в MAX для обсуждения сбоев (до 4: при 1 активном сбое — чат 1, при 2 — чат 2 и т.д.).
            # Обратная совместимость: MAX_ALARM_FA_CHAT_ID считается первым чатом, если не задан MAX_ALARM_FA_CHAT_1_ID.
            "ALARM_FA_CHAT_IDS": _parse_max_fa_chat_ids(),
            # Ссылка-приглашение на чат сбоя (формат https://max.ru/join/...). Если задана — используется в сообщении ALARM_MAIN.
            "ALARM_FA_CHAT_JOIN_LINK": (os.getenv("MAX_ALARM_FA_CHAT_JOIN_LINK", "").strip() or None),
            # Шаблон ссылки на чат. Подставление: {chat_id}. Используется, если get_chat не вернул link и нет ALARM_FA_CHAT_JOIN_LINK.
            "CHAT_LINK_TEMPLATE": (os.getenv("MAX_CHAT_LINK_TEMPLATE", "https://web.max.ru/chat/{chat_id}").strip() or None),
            # Удалять ли чат при закрытии сбоя (False — переиспользовать один чат для теста).
            "ALARM_FA_CHAT_DELETE_ON_CLOSE": os.getenv("MAX_ALARM_FA_CHAT_DELETE_ON_CLOSE", "").strip().lower() in ("1", "true", "yes"),
            # user_id бота в MAX (для модерации ALARM_MAIN: не удалять сообщения бота)
            "BOT_USER_ID": _parse_max_bot_user_id(),
            # Список user_id в MAX, которым разрешено управлять ботом (команды, остановка, продление)
            "ADMIN_IDS": _parse_max_admin_ids(),
            # Включить приём команд из MAX (polling). По умолчанию True, если задан MAX_BOT_TOKEN
            "MANAGEMENT_ENABLED": (
                os.getenv("MAX_MANAGEMENT_ENABLED", "").strip().lower() not in ("0", "false", "no")
                and bool(os.getenv("MAX_BOT_TOKEN", ""))
            ),
        },
        "LINKS": {
            # Шаблон ссылки на задачу Jira, формат: https://jira.example.com/browse/{issue_key}
            "JIRA_BROWSE_URL_TEMPLATE": (os.getenv("JIRA_BROWSE_URL_TEMPLATE", "").strip() or None),
            # Шаблон ссылки на топик Telegram, формат: https://t.me/c/{channel_id}/{topic_id}
            "TELEGRAM_TOPIC_URL_TEMPLATE": (
                os.getenv("TELEGRAM_TOPIC_URL_TEMPLATE", "https://t.me/c/{channel_id}/{topic_id}").strip()
                or None
            ),
            # Ссылка на emergency-чат в KTalk (опционально)
            "KTALK_EMERGENCY_URL": (os.getenv("KTALK_EMERGENCY_URL", "").strip() or None),
        },
    }

    # BUG #6 FIX: Валидация обязательных полей с явными ошибками
    errors = []
    
    if not config["TELEGRAM"]["TOKEN"]:
        errors.append("TELEGRAM_TOKEN не установлен в .env")
    
    if not config["TELEGRAM"]["ALARM_CHANNEL_ID"]:
        errors.append("ALARM_CHANNEL_ID не установлен в .env")
    
    if not config["JIRA"]["TOKEN"]:
        errors.append("JIRA_TOKEN не установлен в .env")
    
    if not config["JIRA"]["LOGIN_URL"]:
        errors.append("JIRA_LOGIN_URL не установлен в .env")
    elif not config["JIRA"]["LOGIN_URL"].startswith(('http://', 'https://')):
        errors.append(f"JIRA_LOGIN_URL имеет некорректный формат: {config['JIRA']['LOGIN_URL']}")
    
    if errors:
        error_msg = "❌ Ошибки конфигурации:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.critical(error_msg)
        raise ValueError(f"Конфигурация некорректна: {', '.join(errors)}")

    # BUG #9 FIX: Полное маскирование токенов в логах
    def mask_token(token: str, visible_chars: int = 4) -> str:
        """Маскирует токен, оставляя только первые visible_chars символов"""
        if not token or len(token) <= visible_chars:
            return "***"
        return token[:visible_chars] + "*" * (len(token) - visible_chars)
    
    masked_token = mask_token(config["TELEGRAM"]["TOKEN"], visible_chars=4)
    masked_jira_token = mask_token(config["JIRA"]["TOKEN"], visible_chars=4)
    masked_confluence_password = mask_token(config["CONFLUENCE"]["PASSWORD"], visible_chars=0)
    masked_jira_password = mask_token(config["JIRA"]["PASSWORD"], visible_chars=0)
    
    logger.info("✅ Конфигурация загружена из .env")
    logger.debug(f"👥 ADMIN_IDS: {admin_ids}")
    logger.debug(f"🕵️ SUPERADMIN_IDS: {superadmin_ids}")
    logger.debug(f"🔑 TELEGRAM_TOKEN: {masked_token}")
    logger.debug(f"🔑 JIRA_TOKEN: {masked_jira_token}")
    if config["CONFLUENCE"]["PASSWORD"]:
        logger.debug(f"🔑 CONFLUENCE_PASSWORD: {masked_confluence_password}")
    if config["JIRA"]["PASSWORD"]:
        logger.debug(f"🔑 JIRA_PASSWORD: {masked_jira_password}")
    
    return config


CONFIG = load_config()


def jira_browse_url(issue_key: str) -> str:
    """Возвращает ссылку на задачу Jira по ключу, используя шаблон из .env или JIRA_LOGIN_URL."""
    key = (issue_key or "").strip()
    if not key:
        return ""
    tmpl = (CONFIG.get("LINKS", {}).get("JIRA_BROWSE_URL_TEMPLATE") or "").strip()
    if tmpl and "{issue_key}" in tmpl:
        try:
            return tmpl.format(issue_key=key)
        except Exception:
            pass
    login_url = (CONFIG.get("JIRA", {}).get("LOGIN_URL") or "").strip()
    if login_url:
        try:
            return urljoin(login_url, f"/browse/{key}")
        except Exception:
            return ""
    return ""


def telegram_topic_url(channel_id: str, topic_id: int) -> str:
    """Возвращает ссылку на тему Telegram по шаблону из .env."""
    cid = str(channel_id or "").strip()
    if cid.startswith("-100"):
        cid = cid[4:]
    tmpl = (CONFIG.get("LINKS", {}).get("TELEGRAM_TOPIC_URL_TEMPLATE") or "").strip()
    if not tmpl:
        return ""
    try:
        return tmpl.format(channel_id=cid, topic_id=topic_id)
    except Exception:
        return ""


def ktalk_emergency_url() -> str:
    """Ссылка на emergency-чат KTalk (опционально)."""
    return (CONFIG.get("LINKS", {}).get("KTALK_EMERGENCY_URL") or "").strip()


def is_admin(user_id: int) -> bool:
    return user_id in CONFIG.get("TELEGRAM", {}).get("ADMIN_IDS", [])


def is_superadmin(user_id: int) -> bool:
    superadmins = CONFIG.get("TELEGRAM", {}).get("SUPERADMIN_IDS", [])
    return user_id in superadmins


def is_max_admin(user_id: int) -> bool:
    """Проверка, что user_id в MAX имеет право управлять ботом (команды из MAX)."""
    max_ids = CONFIG.get("MAX", {}).get("ADMIN_IDS", [])
    return int(user_id) in max_ids