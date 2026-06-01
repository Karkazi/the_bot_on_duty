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


def _parse_max_fa_chat_join_links() -> Dict[str, str]:
    """
    Парсит map chat_id -> invite link для FA-чатов MAX.
    Поддерживает:
    - Явные пары: MAX_ALARM_FA_CHAT_1_ID + MAX_ALARM_FA_CHAT_1_LINK (и 2..4)
    - Устаревший общий MAX_ALARM_FA_CHAT_JOIN_LINK (один и тот же для всех)
    """
    mapping: Dict[str, str] = {}
    for idx in (1, 2, 3, 4):
        cid = (os.getenv(f"MAX_ALARM_FA_CHAT_{idx}_ID", "") or "").strip()
        link = (os.getenv(f"MAX_ALARM_FA_CHAT_{idx}_LINK", "") or "").strip()
        if cid and link:
            mapping[cid] = link

    common = (os.getenv("MAX_ALARM_FA_CHAT_JOIN_LINK", "") or "").strip()
    if common:
        for cid in _parse_max_fa_chat_ids():
            if cid and cid not in mapping:
                mapping[cid] = common
    return mapping


def get_next_max_fa_chat_id(used_chat_ids: set) -> Optional[str]:
    """
    Возвращает первый FA-чат MAX, который НЕ занят ни одним из активных сбоёв.
    Если все чаты заняты — возвращает последний (крайний запасной).

    used_chat_ids — множество str(chat_id), уже назначенных активным сбоям.
    """
    chat_ids = CONFIG.get("MAX", {}).get("ALARM_FA_CHAT_IDS") or []
    if not chat_ids:
        return None
    normalized_used = {str(c).strip() for c in used_chat_ids if c}
    for cid in chat_ids:
        if str(cid).strip() not in normalized_used:
            return str(cid).strip()
    # Все чаты заняты — используем последний как запасной
    logger.warning(
        "[FA_CHAT] Все %d FA-чатов заняты активными сбоями, используем последний (%s)",
        len(chat_ids), chat_ids[-1],
    )
    return str(chat_ids[-1]).strip()


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


def _parse_bool_env(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        logger.warning("Некорректное целое %s=%r, использую %d", name, raw, default)
        return default


def _parse_calendar_digest_times() -> list:
    """CALENDAR_DIGEST_TIMES=10:00,18:00 → [(10, 0), (18, 0)]."""
    raw = (os.getenv("CALENDAR_DIGEST_TIMES", "10:00,18:00") or "").strip()
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            h_s, m_s = part.split(":", 1)
            h, m = int(h_s), int(m_s)
            if 0 <= h <= 23 and 0 <= m <= 59:
                result.append((h, m))
        except ValueError:
            logger.warning("Некорректное время CALENDAR_DIGEST_TIMES, пропуск: %r", part)
    return result or [(10, 0), (18, 0)]


def _parse_max_calendar_admin_ids() -> list:
    """Парсит MAX_CALENDAR_ADMIN_IDS из .env (список user_id в MAX для запросов по новым регламентным работам из Confluence)."""
    s = os.getenv("MAX_CALENDAR_ADMIN_IDS", "")
    ids = []
    for part in (s or "").split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                logger.warning("Некорректный MAX_CALENDAR_ADMIN_ID пропущен: %r", part)
    return ids


def load_config() -> Dict[str, Any]:
    """
    Загружает конфигурацию из переменных окружения (.env файл).
    """
    logger.info("⚙️ Загружаю конфигурацию из .env")

    # Безопасное получение и обработка URL (защита от None)
    confluence_login_url = os.getenv("CONFLUENCE_LOGIN_URL", "https://confluence.example.com/login.action")
    confluence_target_url = os.getenv("CONFLUENCE_TARGET_URL", "https://confluence.example.com/pages/viewpage.action?pageId=0")
    confluence_label_url = (os.getenv("CONFLUENCE_LABEL_URL", "") or "").strip()
    confluence_label_name = (os.getenv("CONFLUENCE_LABEL_NAME", "") or "").strip()
    confluence_label_space = (os.getenv("CONFLUENCE_LABEL_SPACE", "") or "").strip()
    jira_login_url = os.getenv("JIRA_LOGIN_URL", "https://jira.example.com/login.jsp")
    
    config = {
        "CONFLUENCE": {
            "LOGIN_URL": confluence_login_url.strip() if confluence_login_url else "",
            "TARGET_URL": confluence_target_url.strip() if confluence_target_url else "",
            "WORKS_PAGE_ID": (os.getenv("CONFLUENCE_WORKS_PAGE_ID", "") or "").strip() or None,
            # Если задан label — бот будет обходить все pageId с этим label в указанном space.
            # Пример: /label/PUB/calendaritactual
            "LABEL_URL": confluence_label_url,
            "LABEL_NAME": confluence_label_name,
            "LABEL_SPACE": confluence_label_space,
            "USERNAME": (os.getenv("CONFLUENCE_USERNAME", "") or "").strip(),
            "PASSWORD": (os.getenv("CONFLUENCE_PASSWORD", "") or "").strip(),
            "TOKEN": (os.getenv("CONFLUENCE_TOKEN", "") or "").strip(),
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
            # Персональные invite-ссылки для FA-чатов: chat_id -> https://max.ru/join/...
            "ALARM_FA_CHAT_JOIN_LINKS": _parse_max_fa_chat_join_links(),
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
            # user_id в MAX, которым отправляются запросы на оповещение по новым работам из Confluence
            "CALENDAR_ADMIN_IDS": _parse_max_calendar_admin_ids(),
        },
        "CALENDAR": {
            "DIGEST_ENABLED": _parse_bool_env("CALENDAR_DIGEST_ENABLED", default=True),
            "DIGEST_TIMES": _parse_calendar_digest_times(),
        },
        "RESPONSIBLES": {
            "ENABLED": _parse_bool_env("RESPONSIBLES_ENABLED", default=True),
            # Фича-флаг: включать/выключать привлечение ответственных за сервис (CallMasterService).
            # Если 0 — функция не работает (пропускаем notify_alarm_responsibles).
            "CALL_MASTER_SERVICE_ENABLED": _parse_bool_env(
                "CALL_MASTER_SERVICE_ENABLED",
                default=True,
            ),
            "CONFLUENCE_PAGE_ID": (os.getenv("RESPONSIBLES_CONFLUENCE_PAGE_ID", "") or "").strip() or "304990042",
            "CONFLUENCE_PAGE_URL": (os.getenv("RESPONSIBLES_CONFLUENCE_PAGE_URL", "") or "").strip() or None,
            "CACHE_TTL_SEC": max(_parse_int_env("RESPONSIBLES_CACHE_TTL_SEC", 900), 30),
            "NOTIFY_ON_MISS": _parse_bool_env("RESPONSIBLES_NOTIFY_ON_MISS", default=True),
        },
        "LINKS": {
            "JIRA_BROWSE_URL_TEMPLATE": (os.getenv("JIRA_BROWSE_URL_TEMPLATE", "").strip() or None),
            "KTALK_EMERGENCY_URL": (os.getenv("KTALK_EMERGENCY_URL", "").strip() or None),
        },
    }

    errors = []

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
    
    masked_jira_token = mask_token(config["JIRA"]["TOKEN"], visible_chars=4)
    masked_confluence_password = mask_token(config["CONFLUENCE"]["PASSWORD"], visible_chars=0)
    masked_jira_password = mask_token(config["JIRA"]["PASSWORD"], visible_chars=0)

    try:
        from utils.bot_time import get_bot_timezone_name

        logger.info("🕒 Часовой пояс сбоев и работ (BOT_TIMEZONE): %s", get_bot_timezone_name())
    except Exception as e:
        logger.debug("BOT_TIMEZONE: %s", e)
    logger.info("✅ Конфигурация загружена из .env")
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


def ktalk_emergency_url() -> str:
    """Ссылка на emergency-чат KTalk (опционально)."""
    return (CONFIG.get("LINKS", {}).get("KTALK_EMERGENCY_URL") or "").strip()


def is_admin(user_id: int) -> bool:
    return is_max_admin(user_id)


def is_superadmin(user_id: int) -> bool:
    return is_max_admin(user_id)


def is_max_admin(user_id: int) -> bool:
    """Проверка, что user_id в MAX имеет право управлять ботом (команды из MAX)."""
    max_ids = CONFIG.get("MAX", {}).get("ADMIN_IDS", [])
    return int(user_id) in max_ids