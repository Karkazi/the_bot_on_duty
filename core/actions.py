# core/actions.py — остановка и продление событий (канал-агностично)

import logging
from datetime import datetime, timedelta
from typing import Callable, Awaitable, Any, Optional

from bot_state import bot_state
from config import CONFIG
from utils.channel_helpers import send_to_alarm_channels
from handlers.manage.scm import handle_scm_alarm_close
from services.simpleone_service import SimpleOneService
from services.max_archive import process_max_chat_on_alarm_close
from services.max_service import MaxService

logger = logging.getLogger(__name__)

ReplyFn = Callable[[str], Awaitable[Any]]


async def stop_alarm(
    alarm_id: str,
    telegram_bot: Any,
    reply_fn: ReplyFn,
) -> bool:
    """
    Останавливает сбой: SCM, пост на Петлокале, удаление из состояния, сообщение в каналы.
    telegram_bot: экземпляр aiogram Bot для send_to_alarm_channels и handle_scm_alarm_close.
    reply_fn: async (text) -> None — ответ пользователю в текущем канале (TG или MAX).
    Returns: True если сбой найден и остановлен.
    """
    alarm_info = bot_state.active_alarms.get(alarm_id)
    if not alarm_info:
        await reply_fn("❌ Сбой не найден.")
        return False

    # Чат MAX: переименовать в "✅ FA-XXXX", затем архивация (JIRA комментарий или диск), очистка чата и итоговое сообщение
    max_chat_id = alarm_info.get("max_chat_id")
    if max_chat_id is not None:
        max_chat_id = str(max_chat_id).strip() or None
    if not max_chat_id:
        # Сбой без max_chat_id (например, создан до появления привязки или из TG без записи): пробуем первый чат из списка
        chat_ids = (CONFIG.get("MAX") or {}).get("ALARM_FA_CHAT_IDS") or []
        if chat_ids:
            max_chat_id = str(chat_ids[0]).strip() or None
        if max_chat_id:
            logger.info("Сбой %s без max_chat_id в состоянии — используем первый чат из ALARM_FA_CHAT_IDS для архивации", alarm_id)
    jira_key = alarm_info.get("jira_key")
    if not max_chat_id:
        logger.warning(
            "При остановке сбоя %s чат MAX не обработан: у сбоя нет max_chat_id и не заданы MAX_ALARM_FA_CHAT_1_ID…4 в .env. "
            "Задайте чаты для архивации и очистки.",
            alarm_id,
        )
    if max_chat_id:
        try:
            max_svc = MaxService()
            if not max_svc.is_configured():
                logger.warning("MAX не настроен — чат %s не обработан при остановке сбоя %s", max_chat_id, alarm_id)
            else:
                logger.info("Обработка чата MAX для сбоя %s (chat_id=%s): переименование, архивация, очистка", alarm_id, max_chat_id)
                await max_svc.set_chat_title(max_chat_id, f"✅ {alarm_id}"[:200])
                archived_ok = await process_max_chat_on_alarm_close(
                    alarm_id,
                    max_chat_id,
                    jira_key=jira_key,
                )
                if jira_key and not archived_ok:
                    logger.warning(
                        "Сбой %s не закрыт окончательно: экспорт чата MAX в JIRA не завершён (jira_key=%s)",
                        alarm_id, jira_key
                    )
                    await reply_fn(
                        "⚠️ Сбой не закрыт: не удалось полностью перенести чат MAX (вложения) в JIRA. "
                        "Исправьте ошибку интеграции и повторите закрытие."
                    )
                    return False
                logger.info("Чат MAX для сбоя %s обработан", alarm_id)
        except Exception as e:
            logger.warning("Ошибка обработки чата MAX для сбоя %s: %s", alarm_id, e, exc_info=True)

    await handle_scm_alarm_close(telegram_bot, alarm_id, alarm_info)

    if alarm_info.get("publish_petlocal", True):
        try:
            closed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
            async with SimpleOneService() as simpleone:
                html = simpleone.format_alarm_closed_for_petlocal(
                    alarm_id=alarm_id,
                    issue=alarm_info.get("issue", "не указано"),
                    closed_at=closed_at,
                )
                result = await simpleone.create_portal_post(html)
                if result.get("success"):
                    logger.info("Пост о закрытии сбоя %s опубликован на Петлокале", alarm_id)
                else:
                    logger.warning("Не удалось опубликовать пост на Петлокале: %s", result.get("error"))
        except Exception as e:
            logger.warning("Ошибка при публикации на Петлокале: %s", e, exc_info=True)

    del bot_state.active_alarms[alarm_id]
    text = f"✅ Сбой устранён\n• Проблема: {alarm_info['issue']}"
    if not await send_to_alarm_channels(telegram_bot, text):
        logger.error("Не удалось отправить сообщение о завершении сбоя %s", alarm_id)
    await bot_state.save_state()
    await reply_fn(f"🚨 Сбой {alarm_id} остановлен.")
    return True


async def stop_maintenance(
    work_id: str,
    telegram_bot: Any,
    reply_fn: ReplyFn,
) -> bool:
    """
    Завершает регламентную работу: пост на Петлокале, удаление из состояния, сообщение в каналы.
    """
    maint_info = bot_state.active_maintenances.get(work_id)
    if not maint_info:
        await reply_fn("❌ Работа не найдена.")
        return False

    if maint_info.get("publish_petlocal", True):
        try:
            closed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
            async with SimpleOneService() as simpleone:
                html = simpleone.format_maintenance_closed_for_petlocal(
                    work_id=work_id,
                    description=maint_info.get("description", "не указано"),
                    closed_at=closed_at,
                )
                result = await simpleone.create_portal_post(html)
                if result.get("success"):
                    logger.info("Пост о завершении работы %s опубликован на Петлокале", work_id)
                else:
                    logger.warning("Не удалось опубликовать пост на Петлокале: %s", result.get("error"))
        except Exception as e:
            logger.warning("Ошибка при публикации на Петлокале: %s", e, exc_info=True)

    del bot_state.active_maintenances[work_id]
    text = f"✅ <b>Работа завершена</b>\n• <b>Описание:</b> {maint_info['description']}"
    if not await send_to_alarm_channels(telegram_bot, text):
        logger.error("Не удалось отправить сообщение о завершении работы %s", work_id)
    await bot_state.save_state()
    await reply_fn(f"🔧 Работа {work_id} остановлена.")
    return True


def _parse_fix_time(alarm_info: dict, alarm_id: str) -> Optional[datetime]:
    v = alarm_info.get("fix_time")
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            pass
    return None


async def extend_alarm(
    alarm_id: str,
    minutes: int,
    telegram_bot: Any,
    reply_fn: ReplyFn,
) -> bool:
    """
    Продлевает сбой на указанное количество минут.
    Returns: True если сбой найден и продлён.
    """
    alarm = bot_state.active_alarms.get(alarm_id)
    if not alarm:
        await reply_fn("❌ Сбой не найден.")
        return False

    old_end = _parse_fix_time(alarm, alarm_id)
    if not old_end:
        await reply_fn("❌ Некорректное время завершения сбоя.")
        return False

    new_end = old_end + timedelta(minutes=minutes)
    alarm["fix_time"] = new_end.isoformat()
    if "reminder_sent_for" in alarm:
        del alarm["reminder_sent_for"]

    text = (
        f"🔄 <b>Сбой продлён</b>\n"
        f"• <b>Проблема:</b> {alarm['issue']}\n"
        f"• <b>Новое время окончания:</b> {new_end.strftime('%d.%m.%Y %H:%M')}"
    )
    if not await send_to_alarm_channels(telegram_bot, text):
        logger.error("Не удалось отправить сообщение о продлении сбоя %s", alarm_id)
    await bot_state.save_state()
    await reply_fn(f"✅ Сбой {alarm_id} продлён до {new_end.strftime('%d.%m.%Y %H:%M')}.")
    return True


def _parse_end_time(work_info: dict) -> Optional[datetime]:
    v = work_info.get("end_time") or work_info.get("end")
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            pass
    return None


async def extend_maintenance(
    work_id: str,
    minutes: int,
    telegram_bot: Any,
    reply_fn: ReplyFn,
) -> bool:
    """
    Продлевает регламентную работу на указанное количество минут.
    Returns: True если работа найдена и продлена.
    """
    maint = bot_state.active_maintenances.get(work_id)
    if not maint:
        await reply_fn("❌ Работа не найдена.")
        return False

    old_end = _parse_end_time(maint)
    if not old_end:
        await reply_fn("❌ Некорректное время окончания работы.")
        return False

    new_end = old_end + timedelta(minutes=minutes)
    maint["end_time"] = new_end.isoformat()
    if "end" in maint:
        maint["end"] = new_end.isoformat()
    if "reminder_sent_for" in maint:
        del maint["reminder_sent_for"]

    text = (
        f"🔄 <b>Работа продлена</b>\n"
        f"• <b>Описание:</b> {maint['description']}\n"
        f"• <b>Новое время окончания:</b> {new_end.strftime('%d.%m.%Y %H:%M')}"
    )
    if not await send_to_alarm_channels(telegram_bot, text):
        logger.error("Не удалось отправить сообщение о продлении работы %s", work_id)
    await bot_state.save_state()
    await reply_fn(f"✅ Работа {work_id} продлена до {new_end.strftime('%d.%m.%Y %H:%M')}.")
    return True
