"""
Проверка доступа к Confluence: загружает календарь регламентных работ и печатает
последнюю строку таблицы (при добавлении через бота строка вставляется в конец tbody).

Запуск из корня проекта:
  python scripts/confluence_last_work.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import CONFIG  # noqa: E402
from services.confluence_service import (  # noqa: E402
    fetch_page_storage,
    get_confluence_calendar_page_ids,
    parse_works_table,
)


def _print_work(page_id: str, row: dict) -> None:
    print(f"pageId: {page_id}")
    print(f"  work_id:        {row.get('work_id', '—')}")
    print(f"  описание:       {row.get('description', '—')}")
    print(f"  начало:         {row.get('start_time_str', '—')}")
    print(f"  окончание:      {row.get('end_time_str', '—')}")
    print(f"  ответственный:  {row.get('owner') or '—'}")
    print(f"  сервисы:        {row.get('unavailable_services', '—')}")
    print(f"  оповещения:     {row.get('notify') or '—'}")
    inform = row.get("inform_at_str") or "—"
    print(f"  информирование: {inform}")


async def main() -> int:
    conf = CONFIG.get("CONFLUENCE", {}) or {}
    login = (conf.get("LOGIN_URL") or "").strip()
    has_auth = bool(conf.get("TOKEN") or (conf.get("USERNAME") and conf.get("PASSWORD")))
    if not login or not has_auth:
        print(
            "Confluence не настроен: укажите CONFLUENCE_LOGIN_URL и "
            "CONFLUENCE_TOKEN или CONFLUENCE_USERNAME + CONFLUENCE_PASSWORD в .env"
        )
        return 1

    page_ids = await get_confluence_calendar_page_ids()
    if not page_ids:
        print("Список страниц календаря пуст.")
        return 1

    print(f"Страниц календаря: {len(page_ids)} ({', '.join(page_ids)})\n")

    any_ok = False
    for page_id in page_ids:
        storage = await fetch_page_storage(page_id)
        if storage is None:
            print(f"[{page_id}] не удалось загрузить storage (проверьте права и URL).\n")
            continue
        rows = parse_works_table(storage)
        if not rows:
            print(f"[{page_id}] таблица работ пуста или не распознана.\n")
            continue
        any_ok = True
        last = rows[-1]
        print("Последняя строка таблицы на странице (последняя в разметке = обычно последняя добавленная):")
        _print_work(page_id, last)
        print()

    if not any_ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
