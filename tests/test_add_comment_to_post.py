"""
Скрипт для тестирования публикации поста о закрытии сбоя на Петлокале.
Раньше тестировалось добавление комментариев; теперь все сообщения — отдельные посты.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.simpleone_service import SimpleOneService
from config import CONFIG


async def test_closure_post():
    """Тестирование публикации поста о закрытии сбоя на Петлокале"""
    print("=" * 70)
    print("Тестирование публикации поста о закрытии на Петлокале")
    print("=" * 70)

    simpleone_config = CONFIG.get("SIMPLEONE", {})
    base_url = simpleone_config.get("BASE_URL")
    token = simpleone_config.get("TOKEN")

    if not base_url or not token:
        print("\n❌ Ошибка: SimpleOne не настроен (SIMPLEONE_BASE_URL, SIMPLEONE_TOKEN)")
        return

    print(f"\n⚙️  Base URL: {base_url}")
    print(f"   Token: {'*' * 20}...{token[-4:] if len(token) > 4 else '***'}")
    print("\n🔄 Публикация тестового поста «Сбой устранён»...")

    try:
        async with SimpleOneService() as simpleone:
            html = simpleone.format_alarm_closed_for_petlocal(
                alarm_id="TEST-001",
                issue="Тестовый сбой",
                closed_at="02.02.2026 12:00"
            )
            result = await simpleone.create_portal_post(html)
            if result.get("success"):
                print("\n✅ Пост успешно опубликован на Петлокале")
                print(f"   Статус: {result.get('status')}")
            else:
                print("\n❌ Ошибка публикации:", result.get("error", "Неизвестная ошибка"))
    except Exception as e:
        print(f"\n❌ Исключение: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(test_closure_post())
