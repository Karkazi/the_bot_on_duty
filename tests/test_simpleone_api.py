"""
Тестовый скрипт для проверки публикации постов в SimpleOne (Петлокал).
Все сообщения публикуются отдельными постами (в т.ч. о закрытии сбоев/работ).
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.simpleone_service import SimpleOneService
from config import CONFIG


async def test_simpleone_api():
    """Тестирование публикации поста на Петлокале"""
    print("=" * 70)
    print("Тестирование публикации поста SimpleOne (Петлокал)")
    print("=" * 70)

    simpleone_config = CONFIG.get("SIMPLEONE", {})
    base_url = simpleone_config.get("BASE_URL")
    token = simpleone_config.get("TOKEN")

    if not base_url or not token:
        print("❌ Ошибка: SimpleOne не настроен (SIMPLEONE_BASE_URL, SIMPLEONE_TOKEN)")
        return

    print(f"\n1. Конфигурация:")
    print(f"   Base URL: {base_url}")
    print(f"   Token: {'*' * 20}...{token[-4:] if len(token) > 4 else '***'}")

    print("\n2. Публикация тестового поста о закрытии сбоя...")
    try:
        async with SimpleOneService() as simpleone:
            html = simpleone.format_alarm_closed_for_petlocal(
                alarm_id="TEST-API",
                issue="Тестовый сбой для проверки API",
                closed_at="02.02.2026 12:00"
            )
            result = await simpleone.create_portal_post(html)
            if result.get("success"):
                print("\n✅ Успешно! Пост опубликован на Петлокале")
                print(f"   Статус: {result.get('status')}")
            else:
                print("\n❌ Ошибка!")
                print(f"   Статус: {result.get('status', 'N/A')}")
                print(f"   Ошибка: {result.get('error', 'Неизвестная ошибка')}")
                if "data" in result:
                    print(f"   Детали: {json.dumps(result.get('data'), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"\n❌ Исключение при тестировании: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("Тестирование завершено")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_simpleone_api())
