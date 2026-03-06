# Бот управления событиями (ПТЕХ)

Telegram- и MAX-бот для управления событиями: технические сбои, регламентные работы и обычные сообщения. Администраторы могут создавать и управлять событиями из **Telegram** или **MAX Messenger**; уведомления публикуются в каналы Telegram и при необходимости дублируются в MAX, на портал Petlocal (SimpleOne), в Jira и в канал SCM.

---

## Возможности

### Два канала управления
- **Telegram** — основной интерфейс (aiogram 3.12): команды, инлайн-кнопки, создание сбоёв/работ/сообщений, управление, просмотр текущих событий.
- **MAX Messenger** — полное дублирование сценариев (при установленном `maxapi`): «Сообщить», «Текущие события», «Управлять», «Помощь». После выбора команды показываются те же инлайн-клавиатуры (тип сообщения, сервис, Jira, SCM, Петлокал, подтверждение). Права задаются через `MAX_ADMIN_IDS` в `.env`.

### Сбои (аварии)
- Описание проблемы, выбор затронутого сервиса из списка (инлайн-кнопки в TG и MAX).
- Опционально: создание задачи в Jira, заведение темы в канале SCM (Telegram).
- Время «Исправим до» (+1 час по умолчанию), напоминания за 5 минут до окончания.
- Публикация в канал Telegram и при настройке — дублирование в канал MAX.
- Опционально: публикация на портале Petlocal (SimpleOne); при закрытии — отдельный пост «Сбой устранён».
- Автозакрытие по статусу задачи в Jira (Fixed); при ручном закрытии — уведомление в канал, обновление темы SCM (иконка через Bot API, при неудаче — изменение названия темы).

### Регламентные работы
- Описание, время начала/окончания, недоступные сервисы.
- Публикация в каналы и на Petlocal (опционально), при закрытии — пост «Работы завершены».
- Продление через кнопки (+30 мин / +1 час) или ручной ввод (TG); в MAX — кнопки.

### Обычные сообщения
- Текст сообщения и опционально **одно фото** (в Telegram — шаг «Приложить картинку?»: отправить фото или «Пропустить»).
- Публикация в канал Telegram (с фото как `send_photo` с подписью при наличии); при настройке — дублирование текста в канал MAX.
- При публикации на Petlocal фото встраивается в пост (HTML, изображение в base64); в MAX шаг «Приложить картинку» есть с кнопкой «Пропустить» (отправка фото из MAX в канал/Петлокал пока не реализована).

### Просмотр и управление
- **Текущие события** — список активных сбоёв и работ с пагинацией (общий список из состояния бота).
- **Управлять** — выбор сбоя или работы → «Остановить» или «Продлить». В Telegram админы видят **все** активные сбои (в т.ч. созданные из MAX); обычные пользователи — только свои.

---

## Архитектура

- **Точка входа:** `main.py` — загрузка состояния, регистрация middleware и роутеров, запуск polling Telegram и при включённой настройке — polling MAX в одной процессе.
- **Handlers (Telegram):** `handlers/` — `start_help`, `alarm_handlers` (создание сбоёв/работ/сообщений), `manage_handlers` (остановка, продление), `current_events`, `maintenance_spinners`. Модули в `handlers/alarm/` (creation, confirmation, calendar, regular_message, maintenance, cancel) и `handlers/manage/` (stop, extend, reminders, scm).
- **Адаптер MAX:** `adapters/max/` — `polling.py` (запуск polling MAX), `handlers.py` (обработка сообщений и callback), `create_flow.py` (сценарий «Сообщить» по шагам), `keyboards.py` (инлайн-кнопки MAX), `sessions.py` (сессии по user_id для сценария).
- **Ядро:** `core/` — `creation.py` (создание сбоя/работы/сообщения, Jira, SCM, каналы), `actions.py` (stop_alarm, stop_maintenance, extend_*), `events.py` (get_active_events_text), `help_text.py`.
- **Сервисы:** `services/` — `alarm_service`, `maintenance_service`, `channel_service` (Telegram-каналы, SCM, дублирование в MAX), `simpleone_service` (Petlocal), `reminder_service`, `max_service` (отправка в канал MAX).
- **Состояние:** `bot_state.py` — активные сбои и работы, сохранение в файл, очередь записи; доступ по `bot_state.active_alarms` / `active_maintenances`, `get_user_active_alarms(user_id)` и т.д.
- **Конфигурация:** единственный источник конфигурации — `config.py` в корне пакета; загрузка из `.env` (TELEGRAM, JIRA, CONFLUENCE, SIMPLEONE, MAX), проверка обязательных полей, маскирование токенов в логах.
- **Middleware:** обработка ошибок, rate limiting, внедрение зависимостей (bot_state).

---

## Установка и запуск

### Требования
- Python 3.8+
- Зависимости из `requirements.txt` (aiogram 3.12, python-dotenv, requests, aiohttp, pydantic; для MAX — maxapi, brotlicffi).

### Установка (как установить все библиотеки)

1. Перейдите в каталог проекта:
   ```bash
   cd the_bot_on_duty
   ```

2. Создайте виртуальное окружение (рекомендуется):
   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux/macOS
   # или на Windows: venv\Scripts\activate
   ```

3. Установите все зависимости из `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```

   Либо без виртуального окружения, из каталога с проектом:
   ```bash
   cd the_bot_on_duty
   pip install -r requirements.txt
   ```

### Конфигурация (.env)

Создайте файл `.env` в корне проекта (или в каталоге `the_bot_on_duty`, в зависимости от того, откуда запускается приложение).

**Обязательные переменные:**

```env
# Telegram
TELEGRAM_TOKEN=ваш_токен_бота
ALARM_CHANNEL_ID=-1001234567890
ADMIN_IDS=123456789,987654321
SUPERADMIN_IDS=123456789

# Jira
JIRA_TOKEN=ваш_jira_token
JIRA_LOGIN_URL=https://jira.example.com/login.jsp
JIRA_USERNAME=username
```

**Опционально:**

```env
# Канал SCM (темы по сбоям; иконки тем меняются через Bot API)
SCM_CHANNEL_ID=-1001234567890

# SimpleOne / Petlocal
SIMPLEONE_BASE_URL=https://simpleone.example.com
SIMPLEONE_TOKEN=ваш_token
SIMPLEONE_GROUP_ID=group_id
# Автоперевыпуск токена (~120 мин жизни):
SIMPLEONE_USERNAME=std\username
SIMPLEONE_PASSWORD=пароль

# MAX Messenger (дублирование в канал + управление из MAX)
MAX_BOT_TOKEN=токен_бота_MAX
MAX_ALARM_CHANNEL_ID=id_канала_в_MAX
MAX_ADMIN_IDS=123456789
# Чат ALARM_MAIN: уведомления о новых сбоях (FA-XXXX); только посты бота и админов
MAX_ALARM_MAIN_CHAT_ID=id_чата_ALARM_MAIN
# Чаты для обсуждения сбоёв (FA-XXXX): до 4 чатов. При создании сбоя выбирается по числу активных (1 активный → чат 1, 2 → чат 2, 3 → чат 3, 4+ → чат 4). В ALARM_MAIN уходит ссылка на выбранный чат.
# Устаревшее имя MAX_ALARM_FA_CHAT_ID считается первым чатом, если не задан MAX_ALARM_FA_CHAT_1_ID.
MAX_ALARM_FA_CHAT_1_ID=-70000000000000
# Ссылки/шаблоны ссылок (рекомендуется задавать явно)
# JIRA_BROWSE_URL_TEMPLATE=https://jira.example.com/browse/{issue_key}
# TELEGRAM_TOPIC_URL_TEMPLATE=https://t.me/c/{channel_id}/{topic_id}
# KTALK_EMERGENCY_URL=https://ktalk.example.com/emergency
# icon_custom_emoji_id для тем SCM
# TELEGRAM_TOPIC_ICON_DONE_ID=1234567890123456789
# TELEGRAM_TOPIC_ICON_FIRE_ID=1234567890123456789
# MAX_ALARM_FA_CHAT_2_ID=...
# MAX_ALARM_FA_CHAT_3_ID=...
# MAX_ALARM_FA_CHAT_4_ID=...
# Ссылка-приглашение на чат сбоя в MAX (формат https://max.ru/join/...). Подставляется в сообщение «Чат сбоя: MAX (ссылка)».
# MAX_ALARM_FA_CHAT_JOIN_LINK=https://max.ru/join/Z2-uEJHG24ySH7yAshLDGair0kKYLp4F7-F_97pkYeo
# Шаблон ссылки на чат, если API не вернул link и JOIN_LINK не задан. Подставление: {chat_id}.
# MAX_CHAT_LINK_TEMPLATE=https://web.max.ru/chat/{chat_id}
# user_id бота в MAX (для модерации ALARM_MAIN: не удалять сообщения бота)
# MAX_BOT_USER_ID=123456789
# MAX_API_URL по умолчанию https://platform-api.max.ru
```

Полный список переменных и проверки — в `config.py`.

### Запуск

Запускайте бота **из корня проекта** (каталог, в котором лежит `main.py`), чтобы пути к файлам (например, `data/state.json`, `.env`) и логи работали корректно:

```bash
cd the_bot_on_duty
python main.py
```

При наличии `MAX_BOT_TOKEN` и включённом управлении из MAX в том же процессе поднимается polling MAX; для этого нужны пакеты `maxapi` и `brotlicffi` (`pip install maxapi brotlicffi`).

#### Запуск в screen (xterm)

Чтобы бот работал в фоне и не останавливался при закрытии терминала:

1. **Откройте xterm** (или другой терминал).

2. **Запустите screen** (при желании — с именем сессии):
   ```bash
   screen -S bot_duty
   ```
   Или просто `screen` — сессия будет без имени.

3. **Перейдите в каталог проекта и запустите бота:**
   ```bash
   cd /путь/к/the_bot_on_duty
   python main.py
   ```

4. **Отсоединиться от screen** (бот продолжит работать):
   - Нажмите **Ctrl+A**, затем **D**.

5. **Вернуться к сессии с ботом:**
   ```bash
   screen -r bot_duty
   ```
   Если сессия одна — достаточно `screen -r`.

6. **Остановить бота:** зайти в сессию (`screen -r`), нажать **Ctrl+C**, при необходимости выйти из screen: **Ctrl+A**, затем **K** (убить текущее окно) или ввести `exit`.

**Полезные команды screen:**
- `screen -ls` — список сессий
- `screen -r bot_duty` — подключиться к сессии `bot_duty`
- `screen -d -r bot_duty` — отвязать сессию от другого терминала и подключить к текущему

---

## Команды и сценарии

### Telegram
- `/start`, `/help` — приветствие и справка.
- «📢 Сообщить» / `/new_message` — создание сбоя, работы или обычного сообщения (пошаговый сценарий с кнопками).
- «📕 Текущие события» / `/alarm_list` — просмотр активных сбоёв и работ.
- «🛂 Управлять» / `/manage` — выбор сбоя/работы → Остановить / Продлить (админы видят все сбои).

### MAX
- Текстовые команды или кнопки: «Сообщить», «Текущие события», «Управлять», «Помощь». После выбора типа (Сбой/Работа/Обычное) — те же шаги, что в Telegram, с инлайн-кнопками (сервис, Jira, SCM, Петлокал, Подтвердить).

---

## Интеграции

### Jira
- При создании сбоя можно создать задачу в Jira; ключ задачи сохраняется. Автозакрытие сбоя при переходе задачи в статус Fixed (проверка по расписанию).

### SimpleOne (Petlocal)
- Публикация постов о сбоях/работах/сообщениях на портал Petlocal (таблица `c_portal_news`). Для обычных сообщений с фото изображение встраивается в HTML-пост (data URL). При закрытии сбоя/работы — отдельный пост («Сбой устранён» / «Работы завершены»). Токен живёт ~120 минут; при указании `SIMPLEONE_USERNAME` и `SIMPLEONE_PASSWORD` бот перевыпускает токен в фоне (~100 мин) и при 401.

### Иконки тем форума (SCM)
- Смена иконки темы при создании сбоя (🔥) и при закрытии (✅) выполняется через **Bot API** (`editForumTopic`, `icon_custom_emoji_id`). ID эмодзи задаются в `services/channel_service.py` в словаре `BOT_API_ICON_EMOJI_IDS`.

### MAX Messenger
- **Дублирование в канал:** при заданных `MAX_BOT_TOKEN` и `MAX_ALARM_CHANNEL_ID` каждое уведомление в канал Telegram отправляется также в указанный канал MAX (через `services/max_service.py`, вызов из `utils/channel_helpers.py`).
- **Управление из MAX:** при `MAX_MANAGEMENT_ENABLED` (по умолчанию true при наличии `MAX_BOT_TOKEN`) запускается polling MAX (`adapters/max/polling.py`). Пользователи из `MAX_ADMIN_IDS` могут выполнять сценарии «Сообщить», «Текущие события», «Управлять», «Помощь» с инлайн-кнопками.

---

## Тестирование

```bash
pytest
pytest tests/unit/
pytest tests/integration/
pytest --cov=the_bot_on_duty --cov-report=html
```

В `tests/` размещены unit- и integration-тесты, а также скрипты проверки (например, `test_simpleone_api.py`).

---

## Структура проекта

```
the_bot_on_duty/
├── main.py                 # Точка входа: Telegram + опционально MAX polling
├── config.py               # Загрузка CONFIG из .env
├── bot_state.py            # Состояние: active_alarms, active_maintenances, сохранение в файл
├── adapters/
│   └── max/                # Адаптер MAX Messenger
│       ├── polling.py      # Запуск polling MAX
│       ├── handlers.py     # Обработчики сообщений и callback
│       ├── create_flow.py  # Сценарий «Сообщить» по шагам
│       ├── keyboards.py    # Инлайн-клавиатуры MAX
│       └── sessions.py     # Сессии пользователей MAX
├── core/                   # Ядро: создание событий, действия, события, справка
├── handlers/               # Обработчики Telegram
│   ├── alarm/              # Создание сбоёв, работ, обычных сообщений
│   ├── manage/             # Остановка, продление, напоминания, SCM
│   ├── current_events.py   # Просмотр текущих событий
│   └── ...
├── services/               # Сервисы: каналы, Jira, SimpleOne, MAX, напоминания
├── middleware/             # Ошибки, rate limit, DI
├── utils/                  # Валидация, хелперы, Jira, SimpleOne token
├── domain/                 # Константы, состояния
├── keyboards/              # Клавиатуры Telegram (alarm, manage, main)
├── docs/                   # Документация
│   ├── PLAN_DUAL_CHANNEL_TELEGRAM_MAX.md
│   ├── SIMPLEONE_SCRIPTED_REST_API.md
│   └── EXCEL_TRAINING_DATA_SPEC.md
├── tests/                  # Unit, integration, тестовые скрипты
└── requirements.txt
```

---

## Безопасность и ограничения

- Доступ к управлению: в Telegram — по `ADMIN_IDS`/`SUPERADMIN_IDS`, в MAX — по `MAX_ADMIN_IDS`.
- Rate limiting: сообщения и callback — 30 запросов / 10 секунд.
- Токены и пароли в логах маскируются.
- Файлы `*.session` и `.env` не должны попадать в репозиторий.

---

## Документация

- [docs/PLAN_DUAL_CHANNEL_TELEGRAM_MAX.md](docs/PLAN_DUAL_CHANNEL_TELEGRAM_MAX.md) — план и реализация управления из Telegram и MAX.
- [docs/SIMPLEONE_SCRIPTED_REST_API.md](docs/SIMPLEONE_SCRIPTED_REST_API.md) — Scripted REST API SimpleOne (при необходимости комментариев к постам; текущая версия использует отдельные посты).
- [docs/EXCEL_TRAINING_DATA_SPEC.md](docs/EXCEL_TRAINING_DATA_SPEC.md) — спецификация сбора данных для обучения AI по сбоям.

---

## Лицензия

См. [LICENSE](LICENSE).
