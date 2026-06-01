## DEV_NOTES_LOCAL — Git и выкладка duty-bot на сервер

Операторская шпаргалка: как **закоммитить в Git**, **выложить в `main`**, и **обновить бота на сервере**.

Связанные документы:

- [docker_update_instructions.md](./docker_update_instructions.md) — подробно про сборку `duty-bot.tar` на Windows и `docker load` / `docker run`
- [alarm_statistics.md](./alarm_statistics.md), [plan_meeting_bot_roadmap.md](./plan_meeting_bot_roadmap.md)

---

### Оглавление

- [Git: ветки и коммиты](#git-ветки-и-коммиты)
- [Что не коммитить](#что-не-коммитить)
- [Вариант A: Windows → tar → сервер (основной)](#вариант-a-windows--tar--сервер-основной)
- [Вариант B: git pull на сервере + Docker](#вариант-b-git-pull-на-сервере--docker)
- [Вариант C: git pull на сервере без Docker (python)](#вариант-c-git-pull-на-сервере-без-docker-python)
- [Проверка после обновления](#проверка-после-обновления)
- [Типовые ошибки](#типовые-ошибки)

---

### Пути на сервере (эталон)

| Что | Путь |
|-----|------|
| Проект / `.env` | `/root/the_bot_on_duty_2/` |
| Данные (volume) | `/root/the_bot_on_duty_2/data/` |
| Архив образа | `/root/the_bot_on_duty_2/duty-bot.tar` |
| Контейнер | `duty-bot` |
| Репозиторий GitHub | `https://github.com/Karkazi/the_bot_on_duty.git` |

---

## Git: ветки и коммиты

### Зачем ветки

- **`main`** — то, с чего работает прод-сервер (релиз).
- **`develop`** (или ваша `DEV_*`) — разработка и тесты до merge в `main`.

Если ветки `develop` ещё нет:

```bash
git checkout main
git pull origin main
git checkout -b develop
git push -u origin develop
```

### Работа на Windows (PyCharm или PowerShell)

```powershell
cd "C:\Users\m.korolev\PycharmProjects\the_bot_on_dute"

git checkout develop
# или: git checkout -b feature/my-change

git status
git add .
git commit -m "Кратко: зачем изменение (например: Jira TimeEndProblem при закрытии сбоя)"

git push origin develop
```

### Выкатка в прод (`main`)

```powershell
cd "C:\Users\m.korolev\PycharmProjects\the_bot_on_dute"

git checkout main
git pull origin main
git merge develop
# при конфликтах — решить в IDE, затем git add && git commit

git push origin main
```

После `push` в `main` — обновление на сервере одним из вариантов ниже.

---

## Что не коммитить

- **`.env`** — токены и секреты (только на сервере и локально, в Git — `.env.example`).
- **`data/`**, `duty-bot.tar`, `*.log`, `bot.log` — runtime и артефакты сборки.
- Локальные probe-файлы в `data/tmp/` при необходимости добавьте в `.gitignore`.

На сервере при обновлении **`.env` обычно не перезаписывают** — только если добавились новые переменные (сверьте с `.env.example`).

---

## Вариант A: Windows → tar → сервер (основной)

Код на сервер **не клонируется для работы бота** — он внутри Docker-образа. На сервер уезжает **`duty-bot.tar`** (+ при необходимости обновлённый `.env`).

### 1. Локально: убедиться, что в `main` нужный код

```powershell
cd "C:\Users\m.korolev\PycharmProjects\the_bot_on_dute"
git checkout main
git pull origin main
```

### 2. Собрать образ и tar

```powershell
$buildId = Get-Date -Format "yyyy-MM-dd_HH-mm"

docker buildx build --platform linux/amd64 `
  --build-arg BUILD_ID=$buildId `
  -t duty-bot:latest -f Dockerfile .

docker save duty-bot:latest -o duty-bot.tar
```

Подробности, `--no-cache`, ошибки Docker Hub — в [docker_update_instructions.md](./docker_update_instructions.md).

### 3. Перенести на сервер

```powershell
scp .\duty-bot.tar root@SERVER_HOST:/root/the_bot_on_duty_2/duty-bot.tar
```

Если меняли `.env` (новые переменные):

```powershell
scp .\.env root@SERVER_HOST:/root/the_bot_on_duty_2/.env
```

### 4. На сервере: загрузить образ и пересоздать контейнер

```bash
cd /root/the_bot_on_duty_2

docker load -i duty-bot.tar
docker images duty-bot:latest

# Важно: docker restart НЕ подхватывает новый образ
docker stop duty-bot 2>/dev/null || true
docker rm duty-bot 2>/dev/null || true

mkdir -p /root/the_bot_on_duty_2/data

docker run -d --name duty-bot \
  --restart unless-stopped \
  --env-file /root/the_bot_on_duty_2/.env \
  -v /root/the_bot_on_duty_2/data:/app/data \
  duty-bot:latest
```

Убедитесь, что **не крутится второй бот** вне Docker:

```bash
ps aux | grep -E 'main.py|the_bot_on_dute' | grep -v grep
# если есть старый python main.py — остановить (kill / systemd)
```

---

## Вариант B: git pull на сервере + Docker

Если на сервере уже есть клон репозитория (удобно для правок без Windows).

### Первый раз

```bash
cd /root
git clone https://github.com/Karkazi/the_bot_on_duty.git the_bot_on_duty_2
cd /root/the_bot_on_duty_2
git checkout main
nano .env   # скопировать с рабочего .env или из .env.example
mkdir -p data
```

### Обновление

```bash
cd /root/the_bot_on_duty_2
git pull origin main

docker build -t duty-bot:latest -f Dockerfile .

docker stop duty-bot 2>/dev/null || true
docker rm duty-bot 2>/dev/null || true

docker run -d --name duty-bot \
  --restart unless-stopped \
  --env-file /root/the_bot_on_duty_2/.env \
  -v /root/the_bot_on_duty_2/data:/app/data \
  duty-bot:latest
```

---

## Вариант C: git pull на сервере без Docker (python)

Используйте только если бот **намеренно** запускается как `python main.py` (не контейнер).

```bash
cd /root/the_bot_on_duty_2
git pull origin main

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

# в .env:
# BOT_APP_DATA_DIR=/root/the_bot_on_duty_2/data

# остановить старый процесс, затем:
python main.py
```

**Не запускайте одновременно** Docker-контейнер `duty-bot` и `python main.py` — будут дубли и путаница с путями/логами.

---

## Проверка после обновления

```bash
docker ps | grep duty-bot
docker logs --tail 50 duty-bot | grep -E 'BUILD_ID|Каталог данных|Запуск бота'
```

Ожидаемо в логах:

- `BUILD_ID=...` — метка свежей сборки
- `Каталог данных: /app/data`
- `state.json: /app/data/state.json`

На хосте:

```bash
ls -la /root/the_bot_on_duty_2/data/
tail -n 30 /root/the_bot_on_duty_2/data/logs/bot.log
```

Функционально: в MAX — `/start`, кнопки меню, тест закрытия сбоя с Jira (поле `customfield_13120`).

---

## Типовые ошибки

| Симптом | Причина | Что сделать |
|--------|---------|-------------|
| «Старый» код после обновления | только `docker restart` | `docker rm` + `docker run` с новым образом |
| Файлы в `/root/`, а не в `data/` | второй процесс `python main.py` | `ps aux \| grep main.py`, остановить лишний |
| Jira TimeEndProblem не заполнился | старый образ или не задеплоен `jira_close_fa` | проверить `BUILD_ID` в логах, пересобрать tar |
| `TLS handshake timeout` при build | нет доступа к Docker Hub | `docker pull python:3.12-slim`, см. docker_update_instructions |
| Токен «битый» | комментарий в конце строки `.env` | убрать `# ...` с той же строки, что и токен |

---

*Шаблон по мотивам `the_bot_rubik/docs/DEV_NOTES_LOCAL.md`, адаптирован под duty-bot и `/root/the_bot_on_duty_2`.*
