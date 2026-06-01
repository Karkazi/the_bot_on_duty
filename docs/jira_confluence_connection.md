# Подключение бота к Jira и Confluence

Документ описывает, **как в проекте** устроены запросы к Jira и Confluence: какие библиотеки используются, откуда берутся настройки, что положить в `.env`, и минимальные примеры проверки соединения.

---

## Общие принципы

- Конфигурация читается из переменных окружения (файл `.env` в корне проекта подхватывается через **`python-dotenv`** в `config.py`).
- В рантайме доступен словарь **`CONFIG`**: секции **`CONFIG["JIRA"]`** и **`CONFIG["CONFLUENCE"]`**.
- Все HTTP-вызовы к Jira и Confluence в боте выполняются через **`aiohttp`** (асинхронно). Отдельных SDK Atlassian в зависимостях нет.
- Базовый URL API строится от **`JIRA_LOGIN_URL`** / **`CONFLUENCE_LOGIN_URL`**: к корню инстанса дописывается путь `rest/api/2/...` (через `urllib.parse.urljoin`).

Зависимости из `requirements.txt`, задействованные здесь:

| Библиотека        | Роль |
|-------------------|------|
| `aiohttp`         | HTTP-клиент для Jira и Confluence REST API |
| `python-dotenv`   | Загрузка `.env` при старте (`config.py`) |

---

## Jira

### Аутентификация

Используется **API-токен** в заголовке:

```http
Authorization: Bearer <JIRA_TOKEN>
```

Поля **`JIRA_USERNAME`** / **`JIRA_PASSWORD`** в `CONFIG` есть, но **текущий код создания задач, проверки статуса, комментариев и вложений опирается на `JIRA_TOKEN`**. Убедитесь, что токен выдан пользователю с правами на проект **FA** и нужные операции REST.

### Базовый URL

- **`JIRA_LOGIN_URL`** — URL страницы логина (например `https://jira.company.com/login.jsp`).  
  Из него формируется `base_url = urljoin(jira_login_url, '/rest/api/2/')`.

### Где в коде

| Файл | Назначение |
|------|------------|
| `utils/create_jira_fa.py` | `POST .../issue` — создание задачи типа Failure |
| `utils/jira_status_checker.py` | `GET .../issue/{key}` — имя статуса (автозакрытие сбоя) |
| `utils/jira_comment.py` | `POST .../issue/{key}/comment` — комментарий при архивации чата MAX |
| `utils/jira_attachments.py` | `POST .../issue/{key}/attachments` — вложения (+ заголовок `X-Atlassian-Token: no-check`) |

### Переменные `.env` (Jira)

| Переменная | Обязательно для бота | Описание |
|------------|----------------------|----------|
| `JIRA_LOGIN_URL` | да | Базовый URL инстанса (как в примере выше) |
| `JIRA_TOKEN` | да | Personal Access Token / API token для Bearer |
| `JIRA_BROWSE_URL_TEMPLATE` | нет | Ссылки в UI: `https://jira.company.com/browse/{issue_key}` |
| `JIRA_USERNAME` | нет | Зарезервировано в конфиге, основной путь API — токен |
| `JIRA_PASSWORD` | нет | То же |

Константы полей задачи (проект **FA**, тип **Failure**, custom fields) задаются в `domain/constants.py` (`JIRA_PROJECT_KEY`, `JIRA_ISSUE_TYPE`, `JIRA_CUSTOM_FIELDS`).

### Пример скрипта проверки Jira

Сохраните рядом с проектом (или запускайте из корня репозитория), положите рабочий `.env`:

```python
# scripts/check_jira_connection.py  (пример, файл в репозитории не обязателен)
import asyncio
import sys
from pathlib import Path

# корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urllib.parse import urljoin

import aiohttp

from config import CONFIG


async def main() -> None:
    jira = CONFIG.get("JIRA") or {}
    login_url = (jira.get("LOGIN_URL") or "").strip()
    token = (jira.get("TOKEN") or "").strip()
    if not login_url or not token:
        print("Задайте JIRA_LOGIN_URL и JIRA_TOKEN в .env")
        sys.exit(1)

    base = urljoin(login_url, "/rest/api/2/")
    me_url = urljoin(base, "myself")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(me_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            text = await resp.text()
            print("GET /rest/api/2/myself →", resp.status)
            if resp.status == 200:
                print("OK, Jira принимает токен.")
            else:
                print(text[:500])


if __name__ == "__main__":
    asyncio.run(main())
```

Успешный ответ **200** на `myself` подтверждает, что URL и токен корректны.

---

## Confluence

### Аутентификация (два варианта)

1. **Bearer-токен** (приоритетный, если задан):  
   `Authorization: Bearer <CONFLUENCE_TOKEN>`
2. **Basic** (логин/пароль), если токена нет:  
   `aiohttp.BasicAuth(CONFLUENCE_USERNAME, CONFLUENCE_PASSWORD)`

Логика в `services/confluence_service.py`: если `TOKEN` непустой — используется только он; иначе — username/password.

### Базовый URL

- **`CONFLUENCE_LOGIN_URL`** — например `https://confluence.company.com/login.action`.  
  От него строятся URL вида `.../rest/api/content/...`, `.../rest/api/content/search`.

### Календарь работ

- Либо одна страница: **`CONFLUENCE_WORKS_PAGE_ID`** или `pageId` из **`CONFLUENCE_TARGET_URL`**.
- Либо несколько страниц по label: **`CONFLUENCE_LABEL_URL`** (или пара **`CONFLUENCE_LABEL_SPACE`** + **`CONFLUENCE_LABEL_NAME`**), см. `get_confluence_calendar_page_ids()`.

### Где в коде

| Файл | Назначение |
|------|------------|
| `services/confluence_service.py` | Поиск страниц по label, `GET content/{id}?expand=body.storage`, запись строки в таблицу и т.д. |

### Переменные `.env` (Confluence)

| Переменная | Обязательно | Описание |
|------------|-------------|----------|
| `CONFLUENCE_LOGIN_URL` | да* | Корень Confluence для REST |
| `CONFLUENCE_TOKEN` | один из вариантов | PAT/API token (Bearer) |
| `CONFLUENCE_USERNAME` + `CONFLUENCE_PASSWORD` | альтернатива токену | Basic-авторизация |
| `CONFLUENCE_TARGET_URL` | нет | Страница-якорь (из URL берётся `pageId`, если нет `WORKS_PAGE_ID`) |
| `CONFLUENCE_WORKS_PAGE_ID` | нет | Явный ID страницы календаря |
| `CONFLUENCE_LABEL_URL` | нет | URL label для обхода нескольких квартальных страниц |
| `CONFLUENCE_LABEL_NAME` / `CONFLUENCE_LABEL_SPACE` | нет | Альтернатива URL для CQL по label |

\*Для функций календаря без URL и pageId бот просто не сможет загрузить контент.

### Пример скрипта проверки Confluence

```python
# scripts/check_confluence_connection.py  (пример)
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urllib.parse import urljoin

import aiohttp

from config import CONFIG


async def main() -> None:
    conf = CONFIG.get("CONFLUENCE") or {}
    login_url = (conf.get("LOGIN_URL") or "").strip()
    token = (conf.get("TOKEN") or "").strip()
    username = (conf.get("USERNAME") or "").strip()
    password = (conf.get("PASSWORD") or "").strip()
    page_id = (conf.get("WORKS_PAGE_ID") or "").strip()
    if not page_id and (conf.get("TARGET_URL") or "").strip():
        from services.confluence_service import get_confluence_page_id

        page_id = get_confluence_page_id()

    if not login_url:
        print("Задайте CONFLUENCE_LOGIN_URL в .env")
        sys.exit(1)
    if not token and not (username and password):
        print("Задайте CONFLUENCE_TOKEN или CONFLUENCE_USERNAME + CONFLUENCE_PASSWORD")
        sys.exit(1)
    if not page_id:
        print("Задайте CONFLUENCE_WORKS_PAGE_ID или pageId в CONFLUENCE_TARGET_URL")
        sys.exit(1)

    base = urljoin(login_url, "/")
    url = urljoin(base, f"rest/api/content/{page_id}?expand=body.storage")
    headers = {}
    auth = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        auth = aiohttp.BasicAuth(username, password)

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, headers=headers or None, auth=auth, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            print("GET content →", resp.status)
            body = await resp.text()
            if resp.status != 200:
                print(body[:800])
            else:
                print("OK, страница доступна.")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Минимальный фрагмент `.env` (копировать не в прод без правок)

```env
# --- Jira ---
JIRA_LOGIN_URL=https://jira.example.com/login.jsp
JIRA_TOKEN=your_api_token
JIRA_BROWSE_URL_TEMPLATE=https://jira.example.com/browse/{issue_key}

# --- Confluence ---
CONFLUENCE_LOGIN_URL=https://confluence.example.com/login.action
# вариант 1:
CONFLUENCE_TOKEN=your_api_token
# вариант 2 (если без токена):
# CONFLUENCE_USERNAME=user
# CONFLUENCE_PASSWORD=secret

CONFLUENCE_WORKS_PAGE_ID=123456789
# или страница с pageId в URL:
# CONFLUENCE_TARGET_URL=https://confluence.example.com/pages/viewpage.action?pageId=123456789

# Несколько страниц календаря по label (опционально):
# CONFLUENCE_LABEL_URL=https://confluence.example.com/label/SPACE/mylabel
```

Полный шаблон см. в `.env.example` в корне репозитория.

---

## Устранение проблем

| Симптом | Направление проверки |
|---------|----------------------|
| Jira **401** | Неверный или просроченный `JIRA_TOKEN`, либо тип токена не подходит для REST |
| Jira **403** | У пользователя токена нет прав на проект/операцию |
| Jira **400** при создании задачи | Несовпадение опций полей с конфигурацией Jira; в логах бота после правок смотрите тело ответа API |
| Confluence **401** | Токен или логин/пароль; для Cloud/Server разные типы токенов |
| Пустой календарь | Проверить `pageId`, права на чтение страницы, при label — `CONFLUENCE_LABEL_*` и CQL |

---

## Ссылки на исходники

- Загрузка env и сборка `CONFIG`: `config.py`
- Jira: `utils/create_jira_fa.py`, `utils/jira_status_checker.py`, `utils/jira_comment.py`, `utils/jira_attachments.py`
- Confluence: `services/confluence_service.py`
