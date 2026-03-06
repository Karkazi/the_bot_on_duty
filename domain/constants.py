# domain/constants.py
"""
Централизованные константы для всего бота.
Убирает магические строки и числа из кода.
"""

# Форматы даты и времени
DATETIME_FORMAT = "%d.%m.%Y %H:%M"
DATETIME_FORMAT_JIRA = "%Y-%m-%d %H:%M"
TIMEZONE_OFFSET = "+0300"  # UTC+3 (Москва)

# Ограничения валидации
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000
MAX_MESSAGE_TEXT_LENGTH = 2000

# JIRA Custom Fields (ID полей в Jira)
JIRA_CUSTOM_FIELDS = {
    "PROBLEM_LEVEL": "customfield_13117",
    "PROBLEM_SERVICE": "customfield_13937",
    "NAUMEN_FAILURE_TYPE": "customfield_14074",
    "STREAM_1C": "customfield_17317",
    "TIME_START_PROBLEM": "customfield_13119",
    "INFLUENCE": "customfield_17107",
}

# JIRA Project
JIRA_PROJECT_KEY = "FA"
JIRA_ISSUE_TYPE = "Failure"

# Уровни проблем (должны совпадать с config.py)
PROBLEM_LEVEL_POTENTIAL = "Потенциальная недоступность сервиса"
PROBLEM_LEVEL_SLOWDOWN = "Замедление работы сервиса"
PROBLEM_LEVEL_FULL_OUTAGE = "Полная недоступность сервиса"
PROBLEM_LEVEL_PARTIAL_OUTAGE = "Частичная недоступность сервиса"
PROBLEM_LEVEL_ISSUES = "Проблемы в работе сервиса"

# Влияние
INFLUENCE_CLIENTS = "Клиенты"
INFLUENCE_BUSINESS = "Бизнес-функция"
INFLUENCE_EMPLOYEES = "Сотрудники"

# Напоминания
REMINDER_MINUTES_BEFORE = 5
REMINDER_CHECK_INTERVAL = 60  # секунды

# Rate limiting (запросов в time_window секунд)
RATE_LIMIT_REQUESTS_PER_SECOND = 30
RATE_LIMIT_WINDOW_SECONDS = 10

# Retry настройки для HTTP запросов
HTTP_MAX_RETRIES = 3
HTTP_RETRY_DELAY = 1.0  # секунды
HTTP_REQUEST_TIMEOUT = 30  # секунды

# Jira статусы и проверка
# Поддерживаем оба варианта названия статуса (английский и русский)
JIRA_STATUS_FIXED_EN = "Failure Fixed"  # Статус на английском
JIRA_STATUS_FIXED_RU = "Сбой устранён"  # Статус на русском (правильное название из Jira)
JIRA_STATUS_FIXED = JIRA_STATUS_FIXED_RU  # Используем русский вариант по умолчанию
JIRA_STATUS_CHECK_INTERVAL = 30  # Интервал проверки статуса (30 секунд)

# Сообщения об ошибках
ERROR_MESSAGE_TOO_LONG = "⚠️ Сообщение слишком длинное. Максимум {max} символов."
ERROR_INVALID_FORMAT = "⚠️ Неверный формат. Используйте: {format}"
ERROR_ACCESS_DENIED = "❌ У вас нет прав для выполнения этой команды"
ERROR_OPERATION_FAILED = "❌ Не удалось выполнить операцию"

# Спиннеры для выбора времени регламентных работ
MAINTENANCE_TIME_SPINNER_CONFIG = {
    "date": {
        "label": "📅 Дата работ",
        "step": 1,
        "min": 0,
        "max": 365,
        "format": lambda val, now=None: _format_date_offset(val, now)
    },
    "hour_start": {
        "label": "⏰ Время начала (часы)",
        "step": 1,
        "min": 0,
        "max": 23,
        "format": lambda val: f"{val:02d}:00"
    },
    "minute_start": {
        "label": "⏰ Время начала (минуты)",
        "step": 15,
        "min": 0,
        "max": 59,
        "format": lambda val: f":{val:02d}"
    },
    "hour_end": {
        "label": "⏰ Время окончания (часы)",
        "step": 1,
        "min": 0,
        "max": 23,
        "format": lambda val: f"{val:02d}:00"
    },
    "minute_end": {
        "label": "⏰ Время окончания (минуты)",
        "step": 15,
        "min": 0,
        "max": 59,
        "format": lambda val: f":{val:02d}"
    },
    "date_end": {
        "label": "📅 Дата окончания работ",
        "step": 1,
        "min": 0,
        "max": 365,
        "format": lambda val, now=None: _format_date_offset(val, now)
    }
}

# Порядок шагов выбора времени
MAINTENANCE_TIME_STEPS_ORDER = [
    "date",
    "hour_start",
    "minute_start",
    "date_end",
    "hour_end",
    "minute_end"
]


def _format_date_offset(days_offset: int, now=None) -> str:
    """Форматирует смещение дней в читаемую дату"""
    from datetime import datetime, timedelta
    if now is None:
        now = datetime.now()
    target_date = now + timedelta(days=days_offset)
    months = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]
    return f"{target_date.day} {months[target_date.month - 1]}"

