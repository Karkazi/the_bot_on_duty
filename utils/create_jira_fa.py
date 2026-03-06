import asyncio
import json
import sys
import logging
from typing import Optional, Dict, Any
from config import CONFIG
from datetime import datetime
from urllib.parse import urljoin
import aiohttp
from aiohttp import ClientTimeout, ClientError
from domain.constants import (
    JIRA_CUSTOM_FIELDS, JIRA_PROJECT_KEY, JIRA_ISSUE_TYPE,
    DATETIME_FORMAT_JIRA, TIMEZONE_OFFSET,
    HTTP_MAX_RETRIES, HTTP_RETRY_DELAY, HTTP_REQUEST_TIMEOUT
)

logger = logging.getLogger(__name__)


def check_config() -> bool:
    """
    Проверка наличия и корректности конфигурации
    """
    if "JIRA" not in CONFIG:
        logger.error("Отсутствует секция JIRA в конфигурации")
        return False
        
    required_vars = ["LOGIN_URL", "TOKEN"]
    missing_vars = [var for var in required_vars if var not in CONFIG["JIRA"] or not CONFIG["JIRA"][var]]
    
    if missing_vars:
        logger.error(f"Отсутствуют необходимые переменные в конфигурации JIRA: {missing_vars}")
        return False
    
    jira_url = CONFIG.get("JIRA", {}).get("LOGIN_URL", "")
    if not jira_url or not jira_url.strip().startswith(('http://', 'https://')):
        logger.error(f"Некорректный URL Jira: {jira_url}")
        return False
    
    return True


async def create_failure_issue(
    summary: str,
    description: str,
    problem_level: Optional[str] = None,
    problem_service: Optional[str] = None,
    naumen_failure_type: Optional[str] = None,
    stream_1c: Optional[str] = None,
    time_start_problem: Optional[str] = None,
    influence: Optional[str] = None,
    contractor_task_link: Optional[str] = None,
    assignee: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Асинхронное создание задачи типа Failure в проекте FA
    
    Args:
        summary (str): Краткое описание проблемы
        description (str): Подробное описание проблемы
        problem_level (str): Уровень проблемы
        problem_service (str): Затронутый сервис
        naumen_failure_type (str): Тип проблемы в Naumen
        stream_1c (str): Поток 1С
        time_start_problem (str): Время начала проблемы
        influence (str): Влияние на
        contractor_task_link (str): Ссылка на задачу в ТП подрядчика
        assignee (str): Исполнитель
    
    Returns:
        dict: Информация о созданной задаче или None в случае ошибки
    """
    if not check_config():
        logger.error("Конфигурация JIRA некорректна")
        return None
        
    # Базовый URL для API (безопасная обработка)
    jira_url = CONFIG.get("JIRA", {}).get("LOGIN_URL", "").strip()
    if not jira_url:
        logger.error("JIRA_LOGIN_URL не установлен")
        return None
    base_url = urljoin(jira_url, '/rest/api/2/')
        
    # Подготовка данных для создания задачи (используем константы)
    issue_data = {
        "fields": {
            "project": {
                "key": JIRA_PROJECT_KEY
            },
            "summary": summary,
            "description": description,
            "issuetype": {
                "name": JIRA_ISSUE_TYPE
            }
        }
    }
        
    # Добавление опциональных полей (используем константы для custom fields)
    if problem_level:
        issue_data["fields"][JIRA_CUSTOM_FIELDS["PROBLEM_LEVEL"]] = {"value": problem_level}
    if problem_service:
        issue_data["fields"][JIRA_CUSTOM_FIELDS["PROBLEM_SERVICE"]] = {"value": problem_service}
    if naumen_failure_type:
        issue_data["fields"][JIRA_CUSTOM_FIELDS["NAUMEN_FAILURE_TYPE"]] = {"value": naumen_failure_type}
    if stream_1c:
        issue_data["fields"][JIRA_CUSTOM_FIELDS["STREAM_1C"]] = {"value": stream_1c}
    if time_start_problem:
        # Преобразование времени в формат ISO 8601 с часовым поясом
        try:
            dt = datetime.strptime(time_start_problem, DATETIME_FORMAT_JIRA)
            # Добавляем часовой пояс (используем константу)
            issue_data["fields"][JIRA_CUSTOM_FIELDS["TIME_START_PROBLEM"]] = dt.strftime(f"%Y-%m-%dT%H:%M:00.000{TIMEZONE_OFFSET}")
        except ValueError as e:
            logger.error(f"Неверный формат времени: {time_start_problem}, ошибка: {e}")
            return None
    if influence:
        issue_data["fields"][JIRA_CUSTOM_FIELDS["INFLUENCE"]] = {"value": influence}
        
    # Заголовки для запроса
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {CONFIG["JIRA"]["TOKEN"]}'
    }
    
    # Retry логика (используем константы)
    timeout = ClientTimeout(total=HTTP_REQUEST_TIMEOUT)
    last_exception = None
    
    for attempt in range(HTTP_MAX_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                logger.debug(f"Попытка {attempt + 1}/{HTTP_MAX_RETRIES}: Создание задачи в Jira")
                async with session.post(
            urljoin(base_url, 'issue'),
                    json=issue_data,
                    headers=headers
                ) as response:
                    if response.status == 201:
                        created_issue = await response.json()
                        logger.info(f"Задача успешно создана: {created_issue['key']}")
                        return created_issue
                    elif response.status == 401:
                        logger.error("Ошибка аутентификации. Проверьте правильность API токена")
                        error_text = await response.text()
                        logger.debug(f"Ответ сервера: {error_text}")
                        return None
                    elif response.status == 403:
                        logger.error("Ошибка доступа. Проверьте права доступа к проекту")
                        error_text = await response.text()
                        logger.debug(f"Ответ сервера: {error_text}")
                        return None
                    elif response.status == 400:
                        logger.error("Ошибка в данных задачи. Проверьте правильность заполнения полей")
                        try:
                            error_details = await response.json()
                            logger.debug(f"Детали ошибки: {json.dumps(error_details, ensure_ascii=False, indent=2)}")
                        except Exception:
                            error_text = await response.text()
                            logger.debug(f"Текст ответа: {error_text}")
                        return None
                    else:
                        error_text = await response.text()
                        logger.warning(f"Неожиданный статус ответа: {response.status}, текст: {error_text}")
                        # Пробуем повторить для 5xx ошибок
                        if 500 <= response.status < 600:
                            raise ClientError(f"Server error: {response.status}")
                        
        except asyncio.TimeoutError:
            last_exception = f"Timeout при создании задачи (попытка {attempt + 1}/{HTTP_MAX_RETRIES})"
            logger.warning(last_exception)
            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))
        except ClientError as e:
            last_exception = f"Ошибка клиента: {str(e)} (попытка {attempt + 1}/{HTTP_MAX_RETRIES})"
            logger.warning(last_exception)
            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))
        except Exception as e:
            last_exception = f"Неожиданная ошибка: {str(e)} (попытка {attempt + 1}/{HTTP_MAX_RETRIES})"
            logger.error(last_exception, exc_info=True)
            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))
    
    logger.error(f"Не удалось создать задачу после {HTTP_MAX_RETRIES} попыток. Последняя ошибка: {last_exception}")
    return None

def get_input_with_options(prompt, options, allow_empty=False):
    """
    Получение ввода с выбором из списка опций
    
    Args:
        prompt (str): Текст запроса
        options (list): Список доступных опций
        allow_empty (bool): Разрешить пустой ввод
    
    Returns:
        str: Выбранная опция или None
    """
    while True:
        print(f"\n{prompt}")
        for i, option in enumerate(options, 1):
            print(f"{i}. {option}")
        
        choice = input("\nВыберите номер (или Enter для пропуска): ").strip()
        if not choice and allow_empty:
            return None
        
        try:
            index = int(choice) - 1
            if 0 <= index < len(options):
                return options[index]
        except ValueError:
            pass
        
        print(f"Ошибка: Выберите число от 1 до {len(options)}")

def main():
    # Проверка конфигурации
    if not check_config():
        sys.exit(1)
    
    print("\n=== Создание задачи типа Failure ===")
    
    # Получение обязательных полей
    summary = input("\nВведите краткое описание проблемы: ").strip()
    while not summary:
        print("Ошибка: Краткое описание не может быть пустым")
        summary = input("Введите краткое описание проблемы: ").strip()
    
    description = input("\nВведите подробное описание проблемы: ").strip()
    while not description:
        print("Ошибка: Подробное описание не может быть пустым")
        description = input("Введите подробное описание проблемы: ").strip()
    
    # Получение опциональных полей
    problem_levels = [
        "Замедление работы сервиса",
        "Полная недоступность сервиса",
        "Частичная недоступность сервиса",
        "Проблемы в работе сервиса",
        "Потенциальная недоступность сервиса"
    ]
    problem_level = get_input_with_options("Выберите уровень проблемы:", problem_levels, False)
    while not problem_level:
        print("Ошибка: Уровень проблемы обязателен")
        problem_level = get_input_with_options("Выберите уровень проблемы:", problem_levels, False)
    
    problem_services = [
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
    problem_service = get_input_with_options("Выберите затронутый сервис:", problem_services, False)
    while not problem_service:
        print("Ошибка: Затронутый сервис обязателен")
        problem_service = get_input_with_options("Выберите затронутый сервис:", problem_services, False)
    
    naumen_failure_types = [
        "Голосовой канал", "Авторизация", "Softphone", "Анкета", "Кейсы с сайта",
        "Почтовый канал", "Чат (VK, WA, Telegram, Webim)", "Отчёты", "Другое"
    ]
    naumen_failure_type = get_input_with_options("Выберите тип проблемы в Naumen:", naumen_failure_types, True)
    
    stream_1c_options = [
        "Интеграция", "Коммерция", "Маркетинг", "ОПТ", "ПиКК", "Розница (СТЦ/КЦ)",
        "Сервисы оплат", "Складская логистика", "Транспортная логистика",
        "Финансы", "ЭДО"
    ]
    stream_1c = get_input_with_options("Выберите поток 1С:", stream_1c_options, True)
    
    print("\nВыберите время начала проблемы:")
    print("1. Указать вручную")
    print("2. Использовать текущее время")
    
    time_choice = input("\nВыберите вариант (1-2) [2]: ").strip() or "2"
    
    if time_choice == "1":
        time_start_problem = input("\nВведите время начала проблемы (YYYY-MM-DD HH:mm): ").strip()
        if time_start_problem:
            try:
                datetime.strptime(time_start_problem, "%Y-%m-%d %H:%M")
            except ValueError:
                print("Ошибка: Неверный формат даты. Используйте формат YYYY-MM-DD HH:mm")
                time_start_problem = None
    else:
        time_start_problem = datetime.now().strftime("%Y-%m-%d %H:%M")
        print(f"\nУстановлено текущее время: {time_start_problem}")
    
    influence_options = ["Клиенты", "Бизнес-функция", "Сотрудники"]
    influence = get_input_with_options("Выберите влияние на:", influence_options, True)
    
    contractor_task_link = input("\nВведите ссылку на задачу в ТП подрядчика: ").strip()
    
    assignee = input("\nВведите логин исполнителя (или Enter для пропуска): ").strip()
    
    # Создание задачи
    create_failure_issue(
        summary=summary,
        description=description,
        problem_level=problem_level,
        problem_service=problem_service,
        naumen_failure_type=naumen_failure_type,
        stream_1c=stream_1c,
        time_start_problem=time_start_problem,
        influence=influence,
        contractor_task_link=contractor_task_link,
        assignee=assignee
    )

if __name__ == "__main__":
    main() 