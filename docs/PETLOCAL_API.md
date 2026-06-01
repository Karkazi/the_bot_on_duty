# Петлокал (SimpleOne): посты и комментарии через API

Инструкция для публикации постов и комментариев на портале Петлокал через Table API SimpleOne. Проверено на `test-petrovich.simpleone.ru`.

## Настройка `.env`

```env
SIMPLEONE_BASE_URL=https://test-petrovich.simpleone.ru
SIMPLEONE_TOKEN=...
SIMPLEONE_GROUP_ID=176251796307142895
SIMPLEONE_USERNAME=...
SIMPLEONE_PASSWORD=...
```

- **GROUP_ID** — ID группы ленты (например, «Журнал ошибок»). URL портала:  
  `{BASE_URL}/petlocal/?post_group_id={GROUP_ID}`
- Токен обновляется автоматически, если заданы `USERNAME` и `PASSWORD`.

Опционально (если администратор развернёт Scripted REST API для комментариев):

```env
SIMPLEONE_COMMENTS_API_PATH=/api/x_<scope>/petlocal_comments/add_comment
```

Сейчас бот использует прямой Table API — этого достаточно.

## Два идентификатора поста

| ID | Где используется | Пример |
|----|------------------|--------|
| **sys_id** | Создание/чтение поста в `c_portal_news`, хранение в `bot_state` (`petlocal_post_id`) | `177945438992334119` |
| **object_id** | Комментарии в `c_portal_comment`, отображение в UI Петлокала | `026bd370-ba01-6410-0278-306f1889fd27` |

`object_id` **не приходит** в ответе при создании поста — его нужно **вычислить** из `sys_id`.

### Формула object_id (как в UI)

```python
PREFIX = "026bd370-ba01-6410-0278-"
hex_suffix = f"{int(post_sys_id):032x}"[-12:]  # последние 12 hex-символов sys_id
object_id = f"{PREFIX}{hex_suffix}"
```

Пример для `sys_id = 177944959498074447`:

- Неверно (десятичные цифры): `…-959498074447` — API может принять, **в UI не видно**
- Верно (hex): `…-2fff7474394f` — **видно в Петлокале**

В коде бота: `SimpleOneService.petlocal_object_id(post_sys_id)`.

## 1. Создание поста

**Запрос:**

```http
POST {SIMPLEONE_BASE_URL}/rest/v1/table/c_portal_news
Authorization: Bearer {SIMPLEONE_TOKEN}
Content-Type: application/json
```

**Тело:**

```json
{
  "content": "<h2>🚨 Технический сбой</h2>\n<p>...</p>",
  "state": "published",
  "type": "post",
  "group_id": "{SIMPLEONE_GROUP_ID}",
  "title": "Заголовок (опционально)",
  "active": true
}
```

**Ответ (200):** в `data[0]` — поля `sys_id`, `title`, `content`, `group_id`, `author_id`, `sys_created_at` и др.

В Python:

```python
from services.simpleone_service import SimpleOneService

async with SimpleOneService() as svc:
    html = svc.format_alarm_for_petlocal(issue="...", service="...", fix_time="...")
    result = await svc.create_portal_post(html, title="Заголовок")
    post_sys_id = result["created_post"]["sys_id"]  # или через _unwrap_record_value
```

Готовые HTML-шаблоны в `SimpleOneService`:

- `format_alarm_for_petlocal` — сбой
- `format_maintenance_for_petlocal` — регламентные работы
- `format_alarm_closed_for_petlocal` / `format_maintenance_closed_for_petlocal` — закрытие
- `format_regular_message_for_petlocal` — произвольное сообщение

## 2. Добавление комментария к посту

**Запрос:**

```http
POST {SIMPLEONE_BASE_URL}/rest/v1/table/c_portal_comment
Authorization: Bearer {SIMPLEONE_TOKEN}
Content-Type: application/json
```

**Тело:**

```json
{
  "text": "<p class=\"editor-paragraph\"><span style=\"white-space: pre-wrap;\">Текст комментария</span></p>",
  "object_id": "026bd370-ba01-6410-0278-306f1889fd27",
  "author_id": "176181559507123905"
}
```

| Поле | Обязательно | Описание |
|------|-------------|----------|
| `text` | да | HTML, лучше через `format_comment_html()` |
| `object_id` | да | `petlocal_object_id(sys_id поста)` |
| `author_id` | да | sys_id сотрудника (`employee`); если не передать — берётся `author_id` поста |

В Python:

```python
async with SimpleOneService() as svc:
    post_sys_id = "177945438992334119"
    result = await svc.add_portal_comment(post_sys_id, "Текст комментария")
    # result: success, object_id, created_comment, post_sys_id
```

## 3. Проверка

**Пост по sys_id:**

```http
GET {BASE_URL}/rest/v1/table/c_portal_news/{sys_id}
```

**Комментарии к посту:**

```http
GET {BASE_URL}/rest/v1/table/c_portal_comment?sysparm_query=object_id={object_id}&sysparm_limit=20
```

Фильтр `sysparm_query=news={sys_id}` **не работает** как привязка к посту — используйте только `object_id`.

## Быстрый тест из проекта

Из корня репозитория:

```powershell
cd c:\Users\m.korolev\PycharmProjects\the_bot_on_dute
python scripts/petlocal_post_and_comment.py
```

Скрипт создаёт пост «ТЕСТ пост + комментарий бота» и добавляет комментарий. В ленте Петлокала должен отображаться 1 комментарий.

Тексты поста/комментария меняются в константах в начале файла `scripts/petlocal_post_and_comment.py`.

## Интеграция в боте

Реализация: `services/simpleone_service.py`

- `create_portal_post()` — пост
- `add_portal_comment()` — комментарий
- `petlocal_object_id()` — расчёт `object_id`

При создании сбоя с `publish_petlocal=True` сохраняйте `sys_id` поста в state как `petlocal_post_id`, чтобы потом вызывать `add_portal_comment` (например, при продлении или закрытии).

Сейчас продление/закрытие сбоя **не** пишет комментарии на Петлокал — только отдельные посты или канал MAX. Подключение комментариев — отдельная доработка в `core/actions.py` / `core/creation.py`.

## Частые ошибки

| Симптом | Причина |
|---------|---------|
| Комментарий есть в API, в UI «0 комментариев» | Неверный `object_id` (часто подставили последние 12 **десятичных** цифр `sys_id` вместо hex) |
| `422` на `object_id` | Невалидный UUID (обрезана строка, например `[-12:]` применили ко всему UUID, а не к hex-суффиксу) |
| `author_id` обязателен | Не передан и не найден у поста |
| `401` | Истёк токен — обновить `SIMPLEONE_TOKEN` или проверить `USERNAME`/`PASSWORD` |

## Scripted REST API (опционально)

Если Table API по каким-то причинам недоступен для комментариев, администратор SimpleOne может создать API `petlocal_comments` / `add_comment`, которое по `post_sys_id` само читает `object_id` из записи поста на сервере.

После развёртывания укажите `SIMPLEONE_COMMENTS_API_PATH` в `.env`. Реализацию в боте при необходимости добавить в `add_portal_comment()` (сейчас используется только Table API).
