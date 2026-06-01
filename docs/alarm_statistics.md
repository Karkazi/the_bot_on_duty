## Статистика сбоев за период

### Что считает

- Источник: файл истории `data/alarm_history.jsonl` (в каталоге `BOT_APP_DATA_DIR`).
- В отчёт попадают **созданные** сбои за выбранный период (по полю `created_at`).
- Отдельно группируются уточнения сервиса, если сервис = `Другое`.

### Где хранится история

- Docker: `/app/data/alarm_history.jsonl` (на хосте обычно `/root/the_bot_on_duty_2/data/alarm_history.jsonl`).
- Без Docker: `/root/the_bot_on_duty_2/data/alarm_history.jsonl` (если `BOT_APP_DATA_DIR=/root/the_bot_on_duty_2/data`).

### Как вызвать в MAX

- В главном меню есть кнопка `📊 Статистика` (доступно только `MAX_ADMIN_IDS`).
- Периоды:
  - `Сегодня`
  - `7 дней`
  - `30 дней`
  - `Ввести даты` → строкой: `ДД.ММ.ГГГГ-ДД.ММ.ГГГГ`

### Реализация в коде

- Запись истории:
  - `core/creation.py` → `append_alarm_created(...)`
  - `core/actions.py` → `append_alarm_closed(...)`
- Агрегация/форматирование:
  - `services/alarm_history_service.py` → `build_alarm_stats_report(...)`
- MAX UI:
  - `adapters/max/keyboards.py` → `cmd_stats`, `stats_period_menu()`
  - `adapters/max/handlers.py` → обработка `cmd_stats`, `stats_*`

