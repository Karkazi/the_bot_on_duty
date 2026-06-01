## Обновление бота через Docker (сборка на Windows → перенос на сервер → перезапуск)

**Git (коммит → `main` → выкладка):** см. [DEV_NOTES_LOCAL.md](./DEV_NOTES_LOCAL.md).

Этот документ описывает, как обновлять **running**-контейнер `duty-bot`, когда вы вносите изменения в код.

Суть: код лежит внутри Docker image, поэтому при каждом изменении нужно **пересобрать образ** и на сервере **перезапустить контейнер** с новым образом. Состояние бота сохраняется в volume.

**Telegram отключён:** в `.env` можно задать `USED_TELEGRAMM=0` — тогда не запускается polling Telegram, не используются каналы ALARM/SCM и мост MAX→TG; управление — через MAX (и фоновые задачи Jira/SimpleOne/Confluence при наличии настроек). `TELEGRAM_TOKEN` и `ALARM_CHANNEL_ID` при `USED_TELEGRAMM=0` не обязательны.

**Что нужно загружать на сервер:** обычно достаточно только:
- `duty-bot.tar` (собранный Docker image),
- актуальный `.env` (если менялись переменные).

Код проекта отдельно на сервер копировать не нужно — он уже внутри image.

---

## Требования

1) На вашей машине (Windows) работает Docker Desktop и можно собрать образ `linux/amd64`.
2) На сервере установлен Docker Engine.
3) На сервере есть `.env` (вы используете именно `.env`, не `.env.prod`).
4) Состояние бота сохраняется в volume, примонтированном в контейнер в `/app/data` (на хосте: `/root/the_bot_on_duty_2/data`).

---

## Переменные (замените на свои)

- `LOCAL_DUTY_DIR` — папка с проектом на Windows  
  `C:\Users\m.korolev\PycharmProjects\the_bot_on_dute`
- `IMAGE_TAG` — тег образа  
  например `duty-bot:latest`
- `TAR_NAME` — имя архива образа  
  например `duty-bot.tar`
- `SERVER_TAR_PATH` — куда кладём tar на сервере  
  например `/root/the_bot_on_duty_2/duty-bot.tar`
- `SERVER_ENV_FILE` — путь к `.env` на сервере  
  например `~/the_bot_on_duty_2/.env` (или `/root/the_bot_on_duty_2/.env`)
- `SERVER_DATA_DIR` — директория на сервере для volume `/app/data`  
  например `/root/the_bot_on_duty_2/data` (все файлы и логи — здесь, не в `/root/`)

Важно: в `.env` строки с токенами не должны иметь inline-комментариев в конце (`... #Комментарий`), иначе токен может стать “битым” (в вашем случае aiogram ругается на пробелы).

---

## Шаг 1. Пересобрать образ на Windows

Откройте PowerShell и выполните:

```powershell
cd "C:\Users\m.korolev\PycharmProjects\the_bot_on_dute"

# Метка сборки попадёт в лог при старте: BUILD_ID=...
$buildId = Get-Date -Format "yyyy-MM-dd_HH-mm"

docker buildx build --platform linux/amd64 --no-cache `
  --build-arg BUILD_ID=$buildId `
  -t duty-bot:latest -f Dockerfile .

docker save duty-bot:latest -o duty-bot.tar

# Проверка локально перед отправкой на сервер (опционально):
docker run --rm duty-bot:latest python -c "import os; print('BUILD_ID=', os.getenv('BUILD_ID'))"
```

`--no-cache` — если без него Docker мог взять старые слои с кодом. После изменений в Python-коде пересборку лучше делать с `--no-cache`.

### Если сборка падает на `TLS handshake timeout` (Docker Hub)

Если видите ошибку вида:

```text
failed to fetch anonymous token ... auth.docker.io ... TLS handshake timeout
```

Это проблема доступа к Docker Hub (сеть/VPN/прокси/DNS), а не кода.

Что сделать (коротко):

```powershell
docker pull python:3.12-slim
```

- Если `pull` не проходит — почините сеть: попробуйте VPN вкл/выкл, перезапуск Docker Desktop, настройку proxy в Docker Desktop, смену DNS в Docker Engine (например `8.8.8.8`, `1.1.1.1`).
- Когда `pull` заработал — повторите `docker buildx build ...`.

---

## Шаг 2. Перенести `duty-bot.tar` на сервер

Если вы можете scp/WinSCP — перенесите `duty-bot.tar` в `SERVER_TAR_PATH`.

Пример scp (замените хост/путь по вашей схеме):

```powershell
scp .\duty-bot.tar root@SERVER_HOST:/root/
```

Если обновлялись переменные окружения — также перенесите `.env` в `SERVER_ENV_FILE`.

---

## Шаг 3. На сервере загрузить новый образ

```bash
docker load -i /root/the_bot_on_duty_2/duty-bot.tar
```

Проверьте, что образ действительно новый (дата **CREATED** — сегодня):

```bash
docker images duty-bot:latest
```

Запомните **IMAGE ID** (первый столбец) — он понадобится в шаге 5.

---

## Шаг 4. Перезапустить контейнер с новым образом

**Важно:** `docker restart duty-bot` **не** подхватывает новый образ. Нужно **удалить** контейнер и создать заново (`docker run`).

1) Остановить и удалить старый контейнер (если он есть):

```bash
docker stop duty-bot 2>/dev/null || true
docker rm duty-bot 2>/dev/null || true
```

Убедитесь, что не осталось второго процесса бота на хосте (старый запуск без Docker):

```bash
docker ps -a | grep duty-bot
ps aux | grep -E 'main.py|the_bot_on_dute' | grep -v grep
```

Если на сервере параллельно крутится `python main.py` из `/root/the_bot_on_duty_2` — это **старый код с диска**, не из `duty-bot.tar`. Остановите его (`kill` / systemd), иначе будет казаться, что «контейнер старый».

2) Подготовить директорию для данных:

```bash
mkdir -p /root/the_bot_on_duty_2/data
```

3) Запустить контейнер:

```bash
docker run -d --name duty-bot \
  --restart unless-stopped \
  --env-file /root/the_bot_on_duty_2/.env \
  -v /root/the_bot_on_duty_2/data:/app/data \
  duty-bot:latest
```

Один volume на `/app/data`: на хосте это `/root/the_bot_on_duty_2/data` — `state.json`, логи (`logs/bot.log`), `tmp/`, архивы (`archive/`).

В `.env` на сервере (обязательно, для Docker):

```env
BOT_APP_DATA_DIR=/app/data
```

Для запуска **без Docker** (`python main.py` из `/root/the_bot_on_duty_2`):

```env
BOT_APP_DATA_DIR=/root/the_bot_on_duty_2/data
```

Не задавайте `BOT_APP_DATA_DIR=/root` — файлы уйдут в домашний каталог root. Если в `/root/` уже лежат старые `state.json` или `bot.log`, перенесите их в `/root/the_bot_on_duty_2/data/` и перезапустите бота.

---

## Шаг 5. Проверить, что всё запустилось

```bash
docker ps | grep duty-bot
docker logs --tail 50 duty-bot
```

В логах должна быть строка с меткой сборки, например:

```text
Запуск бота (MAX), сборка BUILD_ID=2026-05-22_15-30
```

Сверьте образ контейнера с загруженным (IMAGE ID должны совпадать):

```bash
docker inspect duty-bot --format '{{.Image}}'
docker images --no-trunc duty-bot:latest
```

Проверка изнутри контейнера:

```bash
docker exec duty-bot printenv BUILD_ID
docker exec duty-bot python -c "from services.simpleone_service import SimpleOneService; print('add_portal_comment' in dir(SimpleOneService))"
```

Вторая команда для недавних изменений: `True`, если в образ попал код с комментариями Петлокала.

Если Telegram недоступен — контейнер всё равно должен продолжать работу MAX/фоновых задач (теперь TG polling перезапускается и не валит весь процесс).

Логи файлами: внутри контейнера `/app/data/logs/bot.log` (на хосте: `/root/the_bot_on_duty_2/data/logs/bot.log`). Дублирование в stdout — `docker logs`. Для копирования: `docker cp duty-bot:/app/data/logs/bot.log /root/the_bot_on_duty_2/data/bot.log`.

---

## Важные переменные `.env`

Минимум для вашего режима (управление через MAX, Telegram можно выключать):

```env
USED_TELEGRAMM=0
BOT_TIMEZONE=Europe/Moscow
```

Для корректных ссылок на чаты FA (рекомендуется задавать пары ID+LINK):

```env
MAX_ALARM_FA_CHAT_1_ID=-71063779478219
MAX_ALARM_FA_CHAT_1_LINK=https://max.ru/join/Z2-uEJHG24ySH7yAshLDGair0kKYLp4F7-F_97pkYeo

MAX_ALARM_FA_CHAT_2_ID=-71179371547339
MAX_ALARM_FA_CHAT_2_LINK=https://max.ru/join/U-gq5XR3M5sqknSh77kmHgvU44ukJc_aWjj8CYT5wI0

MAX_ALARM_FA_CHAT_3_ID=-71179389438667
MAX_ALARM_FA_CHAT_3_LINK=https://max.ru/join/ImLora-Dib5h90LxUMeKLe106irC7INCH2ekjB-AByg

MAX_ALARM_FA_CHAT_4_ID=-71179380329163
MAX_ALARM_FA_CHAT_4_LINK=https://max.ru/join/8KLfakLGezWz9ShuftjEeS1790vawEjgEgsyk-V9gJM
```

Ссылки будут браться по `chat_id` с приоритетом над `MAX_ALARM_FA_CHAT_JOIN_LINK`.

---

## Типовые проблемы

### После перезапуска спам старыми работами из Confluence

Причина: в `.../data/state.json` накопились записи `known_maintenances_from_confluence` со статусом `waiting_inform_time` и прошедшим `inform_at` — при старте бот сразу шлёт уведомления дежурным.

С новой версии при старте выполняется очистка (`services/state_cleanup.py`). После деплоя перезапустите контейнер (`docker rm` + `run`).

**Срочно без пересборки образа:** остановите бот, отредактируйте state на сервере:

```bash
docker stop duty-bot
nano /root/the_bot_on_duty_2/data/state.json
```

- В `active_maintenances` удалите работы с прошедшим `end_time` (например `7992`).
- В `known_maintenances_from_confluence` для старых записей поставьте `"status": "inform_missed"` или `"expired"`.

Запустите контейнер снова.

---

### Запустилась «старая» версия бота

| Причина | Что сделать |
|--------|-------------|
| Только `docker restart`, без `rm` + `run` | `docker stop duty-bot && docker rm duty-bot`, затем `docker run ...` заново |
| На сервер залили **старый** `duty-bot.tar` | Проверить дату/размер файла на Windows и на сервере; пересобрать с `--no-cache` |
| `docker load`, но контейнер создан от старого IMAGE ID | `docker inspect duty-bot` → сравнить с `docker images duty-bot:latest` |
| Параллельно работает `python main.py` на хосте | `ps aux \| grep main.py` — остановить лишний процесс |
| Сборка из не той папки проекта | В PowerShell `cd` в актуальный каталог перед `docker buildx build` |
| Кэш Docker при сборке | Добавить `--no-cache` (см. шаг 1) |

Краткая последовательность на сервере после загрузки tar:

```bash
docker load -i /root/the_bot_on_duty_2/duty-bot.tar
docker stop duty-bot; docker rm duty-bot
docker run -d --name duty-bot --restart unless-stopped \
  --env-file /root/the_bot_on_duty_2/.env \
  -v /root/the_bot_on_duty_2/data:/app/data \
  duty-bot:latest
docker logs --tail 30 duty-bot | grep BUILD_ID
```

---

1) `TokenValidationError: Token is invalid! It can't contains spaces.`  
   Причина: в `.env` токен имеет inline-комментарий или пробелы.

2) Сообщения/мост “не идут”  
   Часто причина: TG недоступен → мост TG не может отправлять в SCM-тему. В этом случае сообщения должны попадать в буфер и досылаться после восстановления TG.
