#!/usr/bin/env python3
"""
Создать пост на Петлокале и добавить к нему комментарий (видимый в UI).

Документация: docs/PETLOCAL_API.md
Запуск из корня проекта: python scripts/petlocal_post_and_comment.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import utils.paths_bootstrap  # noqa: F401
from services.simpleone_service import SimpleOneService

POST_TITLE = "ТЕСТ пост + комментарий бота"
COMMENT_TEXT = "Комментарий от бота (должен быть виден в UI)"


async def main() -> int:
    async with SimpleOneService() as svc:
        if not svc._is_configured():
            if not await svc._refresh_token_if_configured():
                print("SimpleOne не настроен (TOKEN или USERNAME+PASSWORD)")
                return 1

        html = svc.format_regular_message_for_petlocal(POST_TITLE)
        post_result = await svc.create_portal_post(html, title=POST_TITLE)
        if not post_result.get("success"):
            print("Ошибка создания поста:", post_result.get("error"))
            return 1

        created = post_result.get("created_post") or {}
        post_sys_id = svc._unwrap_record_value(created.get("sys_id"))
        if not post_sys_id:
            print("Не получен sys_id поста:", post_result)
            return 1

        object_id = svc.petlocal_object_id(str(post_sys_id))
        print("Пост создан")
        print(f"  sys_id: {post_sys_id}")
        print(f"  object_id (для комментария): {object_id}")

        comment_result = await svc.add_portal_comment(post_sys_id, COMMENT_TEXT)
        if not comment_result.get("success"):
            print("Ошибка комментария:", comment_result.get("error"))
            return 1

        comment = comment_result.get("created_comment") or {}
        comment_sys_id = svc._unwrap_record_value(comment.get("sys_id"))
        print("Комментарий добавлен")
        print(f"  comment sys_id: {comment_sys_id}")
        print(f"  object_id: {comment_result.get('object_id')}")
        print("\nПроверьте пост в Петлокале — должен быть 1 комментарий.")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
