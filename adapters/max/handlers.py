# adapters/max/handlers.py — обработчики сообщений MAX (вызов core)

import re
import logging
from typing import TYPE_CHECKING, Optional

from config import CONFIG, is_max_admin
from core import get_help_text, get_active_events_text, stop_alarm, stop_maintenance, extend_alarm, extend_maintenance
from adapters.max.sessions import (
    get_session,
    set_session,
    update_session_data,
    clear_session,
    get_manage_session,
    set_manage_session,
    clear_manage_session,
    get_last_bot_message_id,
    set_last_bot_message_id,
    clear_last_bot_message_id,
)
from adapters.max.create_flow import handle_create_message, _execute_confirmation
from adapters.max.keyboards import (
    main_menu,
    message_type_menu,
    event_list_menu,
    manage_type_menu,
    action_menu,
    extend_duration_menu,
    back_only,
    alarm_list_keyboard,
    maintenance_list_keyboard,
    service_keyboard,
    jira_option_keyboard,
    scm_option_keyboard,
    petlocal_option_keyboard,
    confirmation_keyboard,
    regular_photo_skip_keyboard,
    maintenance_time_method_keyboard,
    create_time_spinner_keyboard_max,
)

if TYPE_CHECKING:
    from maxapi.types import MessageCreated

logger = logging.getLogger(__name__)

# Telegram bot instance для send_to_alarm_channels и SCM (подставляется при запуске polling)
_telegram_bot = None


def set_telegram_bot(bot):
    global _telegram_bot
    _telegram_bot = bot


def _user_id(event: "MessageCreated"):
    """Извлекает user_id отправителя из события MAX."""
    try:
        msg = getattr(event, "message", event)
        sender = getattr(msg, "sender", None)
        if sender is not None:
            uid = getattr(sender, "user_id", None) or getattr(sender, "id", None)
            if uid is not None:
                return int(uid)
        uid = getattr(msg, "user_id", None) or getattr(event, "user_id", None)
        if uid is not None:
            return int(uid)
    except Exception as e:
        logger.warning("Не удалось получить user_id из события MAX: %s", e)
    return None


def _chat_id(event: "MessageCreated"):
    """Извлекает chat_id из события MAX. Пробует get_ids(), recipient, chat, message/event.chat_id."""
    try:
        get_ids = getattr(event, "get_ids", None)
        if callable(get_ids):
            try:
                ids = get_ids()
                if ids and ids[0] is not None:
                    return str(ids[0])
            except Exception:
                pass
        msg = getattr(event, "message", event)
        recipient = getattr(msg, "recipient", None)
        if recipient is not None:
            cid = getattr(recipient, "chat_id", None) or getattr(recipient, "id", None)
            if cid is not None:
                return str(cid)
        chat = getattr(msg, "chat", None)
        if chat is not None:
            cid = getattr(chat, "id", None) or getattr(chat, "chat_id", None)
            if cid is not None:
                return str(cid)
        cid = getattr(msg, "chat_id", None) or getattr(event, "chat_id", None)
        if cid is not None:
            return str(cid)
    except Exception as e:
        logger.warning("Не удалось получить chat_id из события MAX: %s", e)
    return None


def _message_text(event: "MessageCreated") -> str:
    """Текст сообщения (без команды). Проверяет body.text, body['text'], message.text."""
    try:
        msg = getattr(event, "message", event)
        body = getattr(msg, "body", None)
        if body is not None:
            text = getattr(body, "text", None)
            if not text and isinstance(body, dict):
                text = body.get("text")
            if text:
                return (text or "").strip()
        return (getattr(msg, "text", None) or "").strip()
    except Exception:
        return ""


def _first_image_url(event: "MessageCreated") -> Optional[str]:
    """URL первого изображения из вложений сообщения (для пересылки картинок из MAX в TG)."""
    try:
        msg = getattr(event, "message", event)
        body = getattr(msg, "body", None)
        if body is None:
            return None
        attachments = getattr(body, "attachments", None) or []
        if not attachments and isinstance(body, dict):
            attachments = body.get("attachments") or []
        for att in attachments:
            if att is None:
                continue
            atype = getattr(att, "type", None)
            if atype is None and isinstance(att, dict):
                atype = att.get("type")
            if str(atype).lower() != "image":
                continue
            payload = getattr(att, "payload", None)
            if payload is not None:
                url = getattr(payload, "url", None)
                if url and isinstance(url, str) and url.strip().startswith("http"):
                    return url.strip()
            if isinstance(att, dict):
                url = att.get("url") or (att.get("payload") or {}).get("url")
                if url and isinstance(url, str) and url.strip().startswith("http"):
                    return url.strip()
        return None
    except Exception as e:
        logger.debug("Не удалось извлечь URL изображения из события MAX: %s", e)
        return None


def _message_mid(event: "MessageCreated") -> Optional[str]:
    """ID сообщения MAX (mid/id) для дополнительного получения вложений через get_messages."""
    try:
        msg = getattr(event, "message", event)
        body = getattr(msg, "body", None)
        if body is not None:
            mid = getattr(body, "mid", None)
            if mid is None and isinstance(body, dict):
                mid = body.get("mid") or body.get("id")
            if mid is not None:
                return str(mid)
        mid = getattr(msg, "mid", None) or getattr(msg, "id", None)
        if mid is not None:
            return str(mid)
    except Exception as e:
        logger.debug("Не удалось извлечь mid из события MAX: %s", e)
    return None


async def _reply(event, text: str, attachments=None):
    """
    Отправить ответ в чат MAX (текст и опционально вложения).
    Возвращает message_id отправленного сообщения или None (для удаления после ответа пользователя).
    """
    try:
        msg = getattr(event, "message", None)
        if msg and hasattr(msg, "answer"):
            sent = await msg.answer(text, attachments=attachments or None)
            if sent and getattr(sent, "message", None) and getattr(sent.message, "body", None):
                return getattr(sent.message.body, "mid", None)
            return None
    except Exception as e:
        logger.warning("Ответ в MAX через event.message.answer не удался: %s", e)
    # Fallback: отправить через MaxService (без клавиатуры, без message_id)
    chat_id = _chat_id(event)
    if chat_id and text:
        try:
            from services.max_service import MaxService
            svc = MaxService()
            if svc.is_configured():
                await svc.send_message(chat_id, text, strip_html=True)
        except Exception as e:
            logger.warning("Ответ в MAX через MaxService не удался: %s", e)
    return None


def _resolve_attachments(attachments) -> Optional[list]:
    """Преобразует строковый ключ клавиатуры в реальное вложение для MAX."""
    if attachments is None:
        return back_only()
    if not isinstance(attachments, str):
        return attachments
    if attachments == "service_keyboard":
        return service_keyboard()
    if attachments == "jira_keyboard":
        return jira_option_keyboard()
    if attachments == "scm_keyboard":
        return scm_option_keyboard()
    if attachments == "petlocal_keyboard":
        return petlocal_option_keyboard()
    if attachments == "confirmation_keyboard":
        return confirmation_keyboard()
    if attachments == "regular_photo_keyboard":
        return regular_photo_skip_keyboard()
    if attachments == "maintenance_time_method_keyboard":
        return maintenance_time_method_keyboard()
    return back_only()


async def _reply_and_track(event, user_id: int, text: str, attachments=None):
    """
    Удаляет предыдущее сообщение бота (если есть), отправляет новое и сохраняет его message_id.
    """
    last_mid = get_last_bot_message_id(user_id)
    if last_mid:
        try:
            bot = event.message._ensure_bot()
            await bot.delete_message(last_mid)
        except Exception as e:
            logger.debug("MAX: не удалось удалить предыдущее сообщение бота: %s", e)
        clear_last_bot_message_id(user_id)
    mid = await _reply(event, text, _resolve_attachments(attachments))
    if mid:
        set_last_bot_message_id(user_id, mid)


async def _reply_max_callback(event, user_id: int, text: str, attachments=None) -> None:
    """Отправить ответ из callback и сохранить message_id (для удаления при следующем ответе)."""
    att = _resolve_attachments(attachments)
    try:
        sent = await event.message.answer(text, attachments=att)
        if sent and getattr(sent, "message", None) and getattr(sent.message, "body", None):
            mid = getattr(sent.message.body, "mid", None)
            if mid:
                set_last_bot_message_id(user_id, mid)
    except Exception as e:
        logger.warning("MAX callback reply не удался: %s", e)


def _spinner_progress_bar_max(current_step: int, total_steps: int) -> str:
    """Полоска прогресса для спиннера (текст)."""
    filled = "▓" * current_step
    empty = "░" * (total_steps - current_step)
    return f"{filled}{empty} {current_step}/{total_steps}"


def _get_spinner_message_and_attachments_max(uid: int):
    """
    Текст и вложения для текущего шага спиннера по сессии.
    Возвращает (text, attachments) или (None, None) если шаг финальный (нужна финализация).
    """
    from datetime import datetime
    from domain.constants import MAINTENANCE_TIME_SPINNER_CONFIG, MAINTENANCE_TIME_STEPS_ORDER

    sess = get_session(uid)
    if not sess:
        return None, None
    spinner_data = (sess.get("data") or {}).get("maintenance_spinner")
    if not spinner_data:
        return None, None
    step_index = spinner_data.get("current_step_index", 0)
    if step_index >= len(MAINTENANCE_TIME_STEPS_ORDER):
        return None, None
    field_type = MAINTENANCE_TIME_STEPS_ORDER[step_index]
    config = MAINTENANCE_TIME_SPINNER_CONFIG[field_type]
    current_value = spinner_data.get(field_type, config["min"])
    step = config.get("step", 1)
    total = len(MAINTENANCE_TIME_STEPS_ORDER)
    progress = _spinner_progress_bar_max(step_index + 1, total)
    if field_type in ("date", "date_end"):
        value_display = config["format"](current_value, datetime.now())
    else:
        value_display = config["format"](current_value)
    text = (
        f"{progress}\n\n"
        f"{config['label']}\n\n"
        f"Текущее значение: {value_display}\n\n"
        "💡 Нажимайте ⬆️ и ⬇️ для изменения"
    )
    att = create_time_spinner_keyboard_max(field_type, current_value, step)
    return text, att


async def _finalize_max_spinner(event, uid: int) -> None:
    """Завершить выбор времени: записать start_time/end_time, перейти к enter_unavailable_services."""
    from datetime import datetime as dt
    from domain.constants import MAINTENANCE_TIME_STEPS_ORDER
    from utils.maintenance_time_utils import MaintenanceTimeSpinner

    sess = get_session(uid)
    spinner_data = (sess.get("data") or {}).get("maintenance_spinner") or {}
    date_offset = spinner_data.get("date", 0)
    hour_start = spinner_data.get("hour_start", 10)
    minute_start = spinner_data.get("minute_start", 0)
    date_end_offset = spinner_data.get("date_end", 0)
    hour_end = spinner_data.get("hour_end", 12)
    minute_end = spinner_data.get("minute_end", 0)
    start_time = MaintenanceTimeSpinner.build_datetime(date_offset, hour_start, minute_start)
    end_time = MaintenanceTimeSpinner.build_datetime(date_end_offset, hour_end, minute_end)
    now = dt.now()
    if start_time < now:
        spinner_data["current_step_index"] = 0
        update_session_data(uid, maintenance_spinner=spinner_data)
        text, att = _get_spinner_message_and_attachments_max(uid)
        if text and att:
            await event.message.edit(text="⚠️ Время начала уже прошло. Выберите снова.\n\n" + text, attachments=att)
        return
    if end_time <= start_time:
        spinner_data["current_step_index"] = 0
        update_session_data(uid, maintenance_spinner=spinner_data)
        text, att = _get_spinner_message_and_attachments_max(uid)
        if text and att:
            await event.message.edit(text="⚠️ Время окончания должно быть позже начала.\n\n" + text, attachments=att)
        return
    update_session_data(uid, start_time=start_time.isoformat(), end_time=end_time.isoformat())
    set_session(uid, "enter_unavailable_services")
    time_display = MaintenanceTimeSpinner.format_time_display(
        date_offset, hour_start, minute_start, date_end_offset, hour_end, minute_end
    )
    final_text = (
        f"✅ Время регламентных работ:\n\n{time_display}\n\n"
        "🔌 Что будет недоступно во время работ?"
    )
    await event.message.edit(text=final_text, attachments=back_only())


async def _handle_max_spinner_callback(event, uid: int, payload: str) -> None:
    """Обработка callback спиннера: inc/dec/next/prev/cancel. Редактирует сообщение, не удаляет."""
    from domain.constants import MAINTENANCE_TIME_STEPS_ORDER
    from utils.maintenance_time_utils import MaintenanceTimeSpinner

    sess = get_session(uid)
    if not sess or sess.get("step") != "spinner_time":
        return
    data = sess.get("data") or {}
    spinner_data = dict(data.get("maintenance_spinner") or {})
    step_index = spinner_data.get("current_step_index", 0)
    field_type = MAINTENANCE_TIME_STEPS_ORDER[step_index] if step_index < len(MAINTENANCE_TIME_STEPS_ORDER) else None

    if payload == "spinner_cancel":
        update_session_data(uid, maintenance_spinner=None)
        set_session(uid, "enter_start_time")
        await event.message.edit(
            text="🚫 Выбор времени отменён. Введите дату текстом или нажмите Спиннеры снова.",
            attachments=maintenance_time_method_keyboard(),
        )
        return

    if payload == "spinner_prev":
        if step_index == 0:
            update_session_data(uid, maintenance_spinner=None)
            set_session(uid, "enter_start_time")
            await event.message.edit(
                text="🚫 Выбор отменён. Введите дату или нажмите Спиннеры.",
                attachments=maintenance_time_method_keyboard(),
            )
            return
        spinner_data["current_step_index"] = step_index - 1
        update_session_data(uid, maintenance_spinner=spinner_data)
        text, att = _get_spinner_message_and_attachments_max(uid)
        if text and att:
            await event.message.edit(text=text, attachments=att)
        return

    if payload == "spinner_next":
        if step_index >= len(MAINTENANCE_TIME_STEPS_ORDER) - 1:
            await _finalize_max_spinner(event, uid)
            return
        spinner_data["current_step_index"] = step_index + 1
        update_session_data(uid, maintenance_spinner=spinner_data)
        text, att = _get_spinner_message_and_attachments_max(uid)
        if text and att:
            await event.message.edit(text=text, attachments=att)
        return

    if payload.startswith("spinner_inc_") and field_type:
        parts = payload.split("_")
        if len(parts) < 5:
            return
        try:
            current_value = int(parts[-2])
            step_val = int(parts[-1])
            ftype = "_".join(parts[2:-2])
        except (ValueError, IndexError):
            return
        new_value = MaintenanceTimeSpinner.increment_value(ftype, current_value, step_val)
        spinner_data[ftype] = new_value
        update_session_data(uid, maintenance_spinner=spinner_data)
        text, att = _get_spinner_message_and_attachments_max(uid)
        if text and att:
            await event.message.edit(text=text, attachments=att)
        return

    if payload.startswith("spinner_dec_") and field_type:
        parts = payload.split("_")
        if len(parts) < 5:
            return
        try:
            current_value = int(parts[-2])
            step_val = int(parts[-1])
            ftype = "_".join(parts[2:-2])
        except (ValueError, IndexError):
            return
        new_value = MaintenanceTimeSpinner.decrement_value(ftype, current_value, step_val)
        spinner_data[ftype] = new_value
        update_session_data(uid, maintenance_spinner=spinner_data)
        text, att = _get_spinner_message_and_attachments_max(uid)
        if text and att:
            await event.message.edit(text=text, attachments=att)
        return


def _register_handlers(dp):
    """Регистрирует обработчики в диспетчере maxapi."""
    from maxapi.types import MessageCreated, Command
    from maxapi.types.chats import ChatType

    alarm_main_chat_id = (CONFIG.get("MAX") or {}).get("ALARM_MAIN_CHAT_ID")
    max_admin_ids = (CONFIG.get("MAX") or {}).get("ADMIN_IDS") or []
    max_bot_user_id = (CONFIG.get("MAX") or {}).get("BOT_USER_ID")

    def _is_alarm_main(ev) -> bool:
        """Сообщение пришло из чата ALARM_MAIN."""
        if not alarm_main_chat_id:
            return False
        cid = _chat_id(ev)
        return cid is not None and str(cid) == str(alarm_main_chat_id)

    async def _alarm_main_moderate(ev) -> bool:
        """Модерация ALARM_MAIN: удалить сообщение, если автор не бот и не админ. Возвращает True если сообщение удалено."""
        sender_id = getattr(ev.from_user, "user_id", None) or getattr(ev.from_user, "id", None)
        if sender_id is not None:
            sender_id = int(sender_id)
        if sender_id in max_admin_ids:
            return False
        if max_bot_user_id is not None and sender_id == max_bot_user_id:
            return False
        try:
            await ev.message.delete()
            logger.debug("ALARM_MAIN: удалено сообщение от user_id=%s", sender_id)
            return True
        except Exception as e:
            logger.warning("ALARM_MAIN: не удалось удалить сообщение: %s", e)
            return False

    def _is_direct_chat(ev) -> bool:
        """True только для личного чата (диалог). Игнорируем каналы и групповые чаты."""
        chat = getattr(ev, "chat", None)
        if chat is None:
            return False
        return getattr(chat, "type", None) == ChatType.DIALOG

    @dp.message_created(Command("start"))
    async def cmd_start(event: MessageCreated):
        if _is_alarm_main(event):
            await _alarm_main_moderate(event)
            return
        if not _is_direct_chat(event):
            return
        uid = _user_id(event)
        if uid is None:
            await _reply(event, "Не удалось определить пользователя.")
            return
        welcome = (
            "👋 Привет! Я бот для управления событиями и уведомлениями.\n\n"
            "Выберите действие кнопкой ниже или напишите команду (/help — справка)."
        )
        await _reply(event, welcome, attachments=main_menu())

    @dp.message_created(Command("help"))
    async def cmd_help(event: MessageCreated):
        if _is_alarm_main(event):
            await _alarm_main_moderate(event)
            return
        if not _is_direct_chat(event):
            return
        uid = _user_id(event)
        if uid is None:
            await _reply(event, "Не удалось определить пользователя.")
            return
        text = get_help_text(html=False)
        await _reply(event, text, attachments=main_menu())

    # Обработчик нажатий на кнопки инлайн-клавиатуры
    @dp.message_callback()
    async def on_callback(event):
        from maxapi.types import MessageCallback
        from bot_state import bot_state
        if not isinstance(event, MessageCallback):
            return
        if not _is_direct_chat(event):
            return
        payload = getattr(event.callback, "payload", None) or ""
        uid = getattr(event.callback.user, "user_id", None) or getattr(event.callback.user, "id", None)
        if uid is not None:
            uid = int(uid)
        if uid is None:
            try:
                await event.message.answer("Не удалось определить пользователя.")
            except Exception as e:
                logger.warning("MAX callback: не удалось отправить ответ (user unknown): %s", e)
            return
        if not is_max_admin(uid):
            try:
                await event.message.answer(
                    "❌ У вас нет прав для управления ботом из MAX. Обратитесь к администратору."
                )
            except Exception as e:
                logger.warning("MAX callback: не удалось отправить ответ (no admin): %s", e)
            return
        try:
            await event.answer(notification=None)
        except Exception as e:
            logger.warning("MAX callback: не удалось вызвать event.answer: %s", e)

        # Спиннеры времени: не удаляем сообщение, только редактируем
        if payload.startswith("spinner_"):
            await _handle_max_spinner_callback(event, uid, payload)
            return

        # Удаляем сообщение бота с кнопкой — в чате остаётся только следующий ответ
        try:
            await event.message.delete()
        except Exception as e:
            logger.debug("MAX: не удалось удалить сообщение с кнопкой: %s", e)

        # Старт спиннеров времени (после "Спиннеры" на шаге enter_start_time)
        if payload == "maint_time_spinners":
            sess = get_session(uid)
            if sess and sess.get("step") == "enter_start_time" and (sess.get("data") or {}).get("type") == "maintenance":
                from domain.constants import MAINTENANCE_TIME_STEPS_ORDER
                spinner_data = {
                    "date": 0,
                    "hour_start": 10,
                    "minute_start": 0,
                    "date_end": 0,
                    "hour_end": 12,
                    "minute_end": 0,
                    "current_step_index": 0,
                }
                update_session_data(uid, maintenance_spinner=spinner_data)
                set_session(uid, "spinner_time")
                text, att = _get_spinner_message_and_attachments_max(uid)
                if text and att:
                    try:
                        sent = await event.message.answer(text, attachments=att)
                        if sent and getattr(sent, "message", None) and getattr(sent.message, "body", None):
                            mid = getattr(sent.message.body, "mid", None)
                            if mid:
                                set_last_bot_message_id(uid, mid)
                    except Exception as e:
                        logger.warning("MAX spinner start: %s", e)
                return

        if payload == "maint_time_manual":
            sess = get_session(uid)
            if sess and sess.get("step") == "enter_start_time" and (sess.get("data") or {}).get("type") == "maintenance":
                await _reply_max_callback(
                    event, uid,
                    "⏰ Введите дату и время начала:\n"
                    "02.02.2026 14:00 или через 1 час, завтра 10:00",
                    back_only(),
                )
                return

        # Назад в меню — сброс сессий и главное меню
        if payload == "cmd_back":
            clear_session(uid)
            clear_manage_session(uid)
            await _reply_max_callback(event, uid, "Выберите действие:", main_menu())
            return

        if payload == "cmd_help":
            await _reply_max_callback(event, uid, get_help_text(html=False), main_menu())
            return

        if payload == "cmd_events":
            alarms_text, _ = get_active_events_text("alarms", 0, html=False)
            works_text, _ = get_active_events_text("maintenances", 0, html=False)
            await _reply_max_callback(event, uid, alarms_text + "\n\n" + works_text, event_list_menu())
            return

        if payload == "events_alarms":
            text, _ = get_active_events_text("alarms", 0, html=False)
            await _reply_max_callback(event, uid, text, event_list_menu())
            return
        if payload == "events_works":
            text, _ = get_active_events_text("maintenances", 0, html=False)
            await _reply_max_callback(event, uid, text, event_list_menu())
            return
        if payload == "events_refresh":
            alarms_text, _ = get_active_events_text("alarms", 0, html=False)
            works_text, _ = get_active_events_text("maintenances", 0, html=False)
            await _reply_max_callback(event, uid, alarms_text + "\n\n" + works_text, event_list_menu())
            return

        if payload == "cmd_manage":
            set_manage_session(uid, "type")
            await _reply_max_callback(event, uid, "🛂 Выберите тип события:", manage_type_menu())
            return

        if payload == "manage_back":
            step = (get_manage_session(uid) or {}).get("step", "")
            if step in ("action", "extend"):
                set_manage_session(uid, "type")
                await _reply_max_callback(event, uid, "🛂 Выберите тип события:", manage_type_menu())
            else:
                clear_manage_session(uid)
                await _reply_max_callback(event, uid, "Выберите действие:", main_menu())
            return

        if payload == "manage_alarms":
            set_manage_session(uid, "alarm_list")
            alarms = bot_state.active_alarms
            items = [(aid, (alarms[aid].get("issue") or aid)[:40]) for aid in list(alarms.keys())[:10]]
            text = "🚨 Выберите сбой:" if items else "Нет активных сбоёв."
            await _reply_max_callback(event, uid, text, alarm_list_keyboard(items))
            return

        if payload == "manage_works":
            set_manage_session(uid, "work_list")
            works = bot_state.active_maintenances
            items = [(wid, (works[wid].get("description") or wid)[:40]) for wid in list(works.keys())[:10]]
            text = "🔧 Выберите работу:" if items else "Нет активных работ."
            await _reply_max_callback(event, uid, text, maintenance_list_keyboard(items))
            return

        if payload.startswith("select_a_"):
            item_id = payload.replace("select_a_", "", 1)
            set_manage_session(uid, "action", item_id=item_id, item_type="alarm")
            await _reply_max_callback(event, uid, f"🚨 Сбой {item_id}. Выберите действие:", action_menu(item_id, "alarm"))
            return
        if payload.startswith("select_m_"):
            item_id = payload.replace("select_m_", "", 1)
            set_manage_session(uid, "action", item_id=item_id, item_type="maintenance")
            await _reply_max_callback(event, uid, f"🔧 Работа {item_id}. Выберите действие:", action_menu(item_id, "maintenance"))
            return

        if payload.startswith("action_stop_a_"):
            item_id = payload.replace("action_stop_a_", "", 1)
            if not _telegram_bot:
                await _reply_max_callback(event, uid, "❌ Сервис недоступен.", main_menu())
                return
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await stop_alarm(item_id, _telegram_bot, reply_fn)
            clear_manage_session(uid)
            return
        if payload.startswith("action_stop_m_"):
            item_id = payload.replace("action_stop_m_", "", 1)
            if not _telegram_bot:
                await _reply_max_callback(event, uid, "❌ Сервис недоступен.", main_menu())
                return
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await stop_maintenance(item_id, _telegram_bot, reply_fn)
            clear_manage_session(uid)
            return

        if payload.startswith("action_extend_a_"):
            item_id = payload.replace("action_extend_a_", "", 1)
            set_manage_session(uid, "extend", item_id=item_id, item_type="alarm")
            await _reply_max_callback(event, uid, f"⏳ На сколько продлить сбой {item_id}?", extend_duration_menu(item_id, "alarm"))
            return
        if payload.startswith("action_extend_m_"):
            item_id = payload.replace("action_extend_m_", "", 1)
            set_manage_session(uid, "extend", item_id=item_id, item_type="maintenance")
            await _reply_max_callback(event, uid, f"⏳ На сколько продлить работу {item_id}?", extend_duration_menu(item_id, "maintenance"))
            return

        if payload.startswith("extend_30_a_"):
            item_id = payload.replace("extend_30_a_", "", 1)
            if not _telegram_bot:
                await _reply_max_callback(event, uid, "❌ Сервис недоступен.", main_menu())
                return
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await extend_alarm(item_id, 30, _telegram_bot, reply_fn)
            clear_manage_session(uid)
            return
        if payload.startswith("extend_60_a_"):
            item_id = payload.replace("extend_60_a_", "", 1)
            if not _telegram_bot:
                await _reply_max_callback(event, uid, "❌ Сервис недоступен.", main_menu())
                return
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await extend_alarm(item_id, 60, _telegram_bot, reply_fn)
            clear_manage_session(uid)
            return
        if payload.startswith("extend_30_m_"):
            item_id = payload.replace("extend_30_m_", "", 1)
            if not _telegram_bot:
                await _reply_max_callback(event, uid, "❌ Сервис недоступен.", main_menu())
                return
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await extend_maintenance(item_id, 30, _telegram_bot, reply_fn)
            clear_manage_session(uid)
            return
        if payload.startswith("extend_60_m_"):
            item_id = payload.replace("extend_60_m_", "", 1)
            if not _telegram_bot:
                await _reply_max_callback(event, uid, "❌ Сервис недоступен.", main_menu())
                return
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await extend_maintenance(item_id, 60, _telegram_bot, reply_fn)
            clear_manage_session(uid)
            return

        # Сообщить: показать выбор типа с клавиатурой
        if payload == "cmd_report":
            set_session(uid, "select_type")
            await _reply_max_callback(event, uid, "📢 Выберите тип сообщения:", message_type_menu())
            return

        if payload in ("msg_type_alarm", "msg_type_maintenance", "msg_type_regular"):
            num = "1" if payload == "msg_type_alarm" else "2" if payload == "msg_type_maintenance" else "3"
            async def reply_fn(t: str, attachments=None):
                await _reply_max_callback(event, uid, t, attachments)
            await handle_create_message(event, reply_fn, uid, num, telegram_bot=_telegram_bot)
            return

        # Обычное сообщение: пропуск прикрепления фото (в MAX фото пока не отправляется)
        if payload == "regular_skip_photo" and get_session(uid):
            sess = get_session(uid)
            if sess.get("step") == "enter_message_photo" and sess.get("data", {}).get("type") == "regular":
                set_session(uid, "select_petlocal")
                await _reply_max_callback(event, uid, "📢 Публиковать на Петлокале?", petlocal_option_keyboard())
                return

        # Публиковать на Петлокале? (сбой / работа / обычное)
        if payload in ("petlocal_publish", "petlocal_skip") and get_session(uid):
            sess = get_session(uid)
            if sess.get("step") == "select_petlocal":
                update_session_data(uid, publish_petlocal=(payload == "petlocal_publish"))
                set_session(uid, "confirmation")
                await _reply_max_callback(event, uid, "Проверьте данные выше. Отправить?", confirmation_keyboard())
                return

        # Создать задачу в Jira? (при заведении сбоя)
        if payload in ("jira_yes", "jira_no") and get_session(uid):
            sess = get_session(uid)
            if sess.get("step") == "select_jira" and sess.get("data", {}).get("type") == "alarm":
                from datetime import datetime as dt, timedelta
                from domain.constants import DATETIME_FORMAT
                if payload == "jira_yes":
                    update_session_data(uid, create_jira=True)
                    now = dt.now()
                    fix_time = now + timedelta(hours=1)
                    update_session_data(uid, fix_time=fix_time.isoformat())
                    set_session(uid, "select_petlocal")
                    await _reply_max_callback(
                        event, uid,
                        f"✅ Jira будет создана. Исправим до: {fix_time.strftime(DATETIME_FORMAT)}.\n📢 Публиковать на Петлокале?",
                        petlocal_option_keyboard(),
                    )
                else:
                    update_session_data(uid, create_jira=False)
                    set_session(uid, "select_scm")
                    await _reply_max_callback(event, uid, "📋 Завести тему в канале SCM?", scm_option_keyboard())
                return

        # Завести тему в SCM? (при заведении сбоя без Jira)
        if payload in ("scm_create", "scm_skip") and get_session(uid):
            sess = get_session(uid)
            if sess.get("step") == "select_scm" and sess.get("data", {}).get("type") == "alarm":
                from datetime import datetime as dt, timedelta
                update_session_data(uid, create_scm=(payload == "scm_create"))
                now = dt.now()
                fix_time = now + timedelta(hours=1)
                update_session_data(uid, fix_time=fix_time.isoformat())
                set_session(uid, "select_petlocal")
                from domain.constants import DATETIME_FORMAT
                await _reply_max_callback(
                    event, uid,
                    f"Исправим до: {fix_time.strftime(DATETIME_FORMAT)}.\n📢 Публиковать на Петлокале?",
                    petlocal_option_keyboard(),
                )
                return

        # Выбор сервиса при заведении сбоя (инлайн-кнопки)
        if payload.startswith("svc_"):
            from config import PROBLEM_SERVICES
            try:
                idx = int(payload.replace("svc_", "", 1))
                if 0 <= idx < len(PROBLEM_SERVICES):
                    service = PROBLEM_SERVICES[idx]
                    update_session_data(uid, service=service)
                    set_session(uid, "select_jira")
                    await _reply_max_callback(event, uid, "📋 Создать задачу в Jira?", jira_option_keyboard())
                    return
            except (ValueError, IndexError):
                pass
            await _reply_max_callback(event, uid, "Неверный выбор сервиса.", back_only())
            return

        # Подтверждение отправки (кнопка «Подтвердить»)
        if payload == "confirm_send" and get_session(uid):
            sess = get_session(uid)
            if sess.get("step") == "confirmation":
                async def _confirm_reply(t: str, attachments=None):
                    await _reply_max_callback(event, uid, t, attachments if attachments else main_menu())
                await _execute_confirmation(uid, _confirm_reply, _telegram_bot)
                return

        try:
            await _reply_max_callback(event, uid, "Неизвестная команда.", main_menu())
        except Exception as e:
            logger.warning("MAX: не удалось отправить ответ «Неизвестная команда»: %s", e)

    def _is_fa_chat_for_bridge(ev) -> bool:
        """True, если сообщение из чата обсуждения сбоя (FA), куда мостим в TG."""
        from bot_state import bot_state
        cid = _chat_id(ev)
        if not cid:
            return False
        cid_str = str(cid)
        for info in bot_state.active_alarms.values():
            if str(info.get("max_chat_id") or "") == cid_str:
                return True
        return False

    # Один обработчик message_created: личный чат -> сценарий (Опишите проблему и т.д.), чат FA -> мост в TG.
    # Порядок важен: личный чат обрабатываем здесь, чтобы ответ на «Опишите проблему» не забирал мост.
    # Если ALARM_MAIN и FA — один и тот же чат (один id в .env), не модерируем: сообщения должны идти в мост в TG.
    @dp.message_created()
    async def message_created_router(event: MessageCreated):
        if _is_alarm_main(event) and not _is_fa_chat_for_bridge(event):
            await _alarm_main_moderate(event)
            return
        # Личный чат — сценарий «Сообщить», команды, остановить/продлить (text_handlers)
        if _is_direct_chat(event):
            await _handle_direct_chat_message(event)
            return
        # Чат FA по сбою — мост MAX -> TG
        if _is_fa_chat_for_bridge(event):
            await _bridge_max_to_tg_impl(event)
            return
        from bot_state import bot_state
        cid = _chat_id(event)
        if cid:
            logger.debug("MAX message_created: чат %s не личный и не FA (max_chat_id сбоёв: %s)", cid, [str(i.get("max_chat_id") or "") for i in bot_state.active_alarms.values()])

    async def _bridge_max_to_tg_impl(event: MessageCreated):
        from bot_state import bot_state
        from config import CONFIG
        cid = _chat_id(event)
        if not cid or not _telegram_bot:
            if not _telegram_bot and cid:
                logger.warning("Мост MAX->TG: telegram_bot не задан, чат %s", cid)
            return
        cid_str = str(cid)
        for alarm_id, info in list(bot_state.active_alarms.items()):
            if str(info.get("max_chat_id") or "") != cid_str:
                continue
            scm_topic_id = info.get("scm_topic_id")
            scm_channel_id = CONFIG.get("TELEGRAM", {}).get("SCM_CHANNEL_ID")
            if not scm_topic_id or not scm_channel_id:
                logger.warning("Мост MAX->TG: сбой %s — нет scm_topic_id(%s) или SCM_CHANNEL_ID(%s)", alarm_id, scm_topic_id, bool(scm_channel_id))
                return
            msg = getattr(event, "message", event)
            sender = getattr(msg, "sender", None) or getattr(event, "from_user", None)
            sender_id = None
            if sender is not None:
                sender_id = getattr(sender, "user_id", None) or getattr(sender, "id", None)
                if sender_id is not None:
                    sender_id = int(sender_id)
            if max_bot_user_id is not None and sender_id is not None and sender_id == max_bot_user_id:
                return
            sender_name = "MAX"
            if sender is not None:
                full = getattr(sender, "full_name", None)
                if full and str(full).strip():
                    sender_name = str(full).strip()
                else:
                    first = getattr(sender, "first_name", None)
                    last = getattr(sender, "last_name", None)
                    if first or last:
                        sender_name = " ".join(filter(None, [str(first or "").strip(), str(last or "").strip()])).strip() or sender_name
                if sender_name == "MAX" and sender_id is not None:
                    sender_name = f"user_{sender_id}"
            text = _message_text(event)
            image_url = _first_image_url(event)
            message_mid = _message_mid(event)
            all_attachments = []
            try:
                from services.max_media import extract_attachments_from_max_message, download_attachment_max
                all_attachments = extract_attachments_from_max_message(msg)
            except Exception as e:
                logger.debug("Мост MAX->TG: извлечение вложений: %s", e)
            # В ряде случаев MessageCreated не содержит URL вложений (только token).
            # Пробуем восстановить вложения через GET /messages.
            if not image_url and not all_attachments:
                try:
                    from services.max_service import MaxService
                    max_svc = MaxService()
                    if max_svc.is_configured():
                        history = await max_svc.get_messages(cid_str, count=20) or []
                        picked = None
                        if message_mid:
                            for m in history:
                                if str(m.get("mid") or "") == message_mid:
                                    picked = m
                                    break
                        if picked is None and history:
                            picked = history[0]
                        if picked:
                            all_attachments = picked.get("attachments") or []
                            if not image_url:
                                for att in all_attachments:
                                    u = (att.get("url") or "").strip()
                                    if att.get("type") in ("image", "photo") and u.startswith("http"):
                                        image_url = u
                                        break
                            if all_attachments:
                                logger.info(
                                    "Мост MAX->TG: вложения восстановлены через get_messages (mid=%s, count=%s)",
                                    message_mid,
                                    len(all_attachments),
                                )
                except Exception as e:
                    logger.debug("Мост MAX->TG: fallback get_messages не сработал: %s", e)
            import os
            import tempfile
            document_paths = []
            temp_files = []
            for att in all_attachments:
                url = att.get("url") or ""
                if not url or not url.startswith("http"):
                    continue
                # Первое изображение уйдёт как photo_url; остальные и все файлы — как документы
                if url == image_url and att.get("type") in ("image", "photo"):
                    continue
                try:
                    content, name = await download_attachment_max(
                        url,
                        att.get("type", ""),
                        att.get("filename") or "",
                    )
                    if not content:
                        continue
                    ext = os.path.splitext(name)[1] if name and "." in name else ".bin"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, prefix="max_bridge_") as tf:
                        tf.write(content)
                        document_paths.append(tf.name)
                        temp_files.append(tf.name)
                except Exception as e:
                    logger.warning("Мост MAX->TG: скачивание вложения %s: %s", url[:50], e)
            if not text and not image_url and not document_paths:
                logger.debug("Мост MAX->TG: сбой %s — нет текста и нет вложений", alarm_id)
                return
            line = f"[MAX, {sender_name}]: {text}" if text else f"[MAX, {sender_name}]"
            try:
                from services.channel_service import ChannelService
                svc = ChannelService()
                await svc.send_to_scm_topic(
                    _telegram_bot,
                    scm_channel_id,
                    scm_topic_id,
                    line,
                    photo_url=image_url,
                    document_paths=document_paths if document_paths else None,
                )
                logger.info(
                    "Мост MAX->TG: сбой %s, тема %s — отправлено (текст=%s, фото=%s, файлов=%s)",
                    alarm_id, scm_topic_id, bool(text), bool(image_url), len(document_paths),
                )
            except Exception as e:
                logger.warning("Мост MAX->TG: %s", e)
            for f in temp_files:
                try:
                    if os.path.isfile(f):
                        os.unlink(f)
                except Exception:
                    pass
            return
        logger.warning("Мост MAX->TG: чат %s не совпал ни с одним сбоем (max_chat_id: %s)", cid_str, [str(i.get("max_chat_id") or "") for i in bot_state.active_alarms.values()])

    async def _handle_direct_chat_message(event: MessageCreated):
        """Обработка сообщений в личном чате: сценарий «Сообщить», команды, остановить/продлить."""
        uid = _user_id(event)
        if uid is None:
            await _reply(event, "Не удалось определить пользователя.")
            return
        if not is_max_admin(uid):
            await _reply(event, "❌ У вас нет прав для управления ботом из MAX. Обратитесь к администратору.")
            return
        # Текст может быть в message.body.text или message.text — не полагаемся на F.message.body.text
        text = _message_text(event)
        session_exists = bool(get_session(uid))
        if not text and not session_exists:
            return
        text_lower = text.lower().strip()

        # Сценарий «Сообщить»: сессия или команда «сообщить» (удаляем предыдущее сообщение бота, отправляем новое)
        async def _reply_fn(t: str, attachments=None):
            await _reply_and_track(event, uid, t, attachments)
        consumed = await handle_create_message(
            event, _reply_fn, uid, text or "", telegram_bot=_telegram_bot
        )
        if consumed:
            return
        if not text:
            return

        # Список событий: текущие, список, события, сбои, работы
        if text_lower in ("текущие", "список", "события", "сбои", "работы", "📕 текущие события"):
            alarms_text, _ = get_active_events_text("alarms", 0, html=False)
            works_text, _ = get_active_events_text("maintenances", 0, html=False)
            await _reply_and_track(event, uid, alarms_text + "\n\n" + works_text)
            return
        if text_lower == "сбои":
            t, _ = get_active_events_text("alarms", 0, html=False)
            await _reply_and_track(event, uid, t)
            return
        if text_lower == "работы":
            t, _ = get_active_events_text("maintenances", 0, html=False)
            await _reply_and_track(event, uid, t)
            return

        # Остановить <id>
        m_stop = re.match(r"^\s*остановить\s+(\S+)\s*$", text_lower, re.I)
        if m_stop:
            item_id = m_stop.group(1).strip()
            async def reply_fn(txt):
                await _reply_and_track(event, uid, txt)
            if not _telegram_bot:
                await _reply_and_track(event, uid, "❌ Сервис недоступен (нет связи с Telegram ботом).")
                return
            from bot_state import bot_state
            if item_id in bot_state.active_alarms:
                await stop_alarm(item_id, _telegram_bot, reply_fn)
                return
            if item_id in bot_state.active_maintenances:
                await stop_maintenance(item_id, _telegram_bot, reply_fn)
                return
            await _reply_and_track(event, uid, f"❌ Событие с ID «{item_id}» не найдено (ни сбой, ни работа).")
            return

        # Продлить <id> <минуты>
        m_extend = re.match(r"^\s*продлить\s+(\S+)\s+(\d+)\s*$", text_lower, re.I)
        if m_extend:
            item_id = m_extend.group(1).strip()
            try:
                minutes = int(m_extend.group(2))
            except ValueError:
                await _reply_and_track(event, uid, "❌ Укажите число минут, например: продлить FA-1234 30")
                return
            if minutes <= 0 or minutes > 10080:
                await _reply_and_track(event, uid, "❌ Укажите минуты от 1 до 10080 (неделя).")
                return
            async def reply_fn(txt):
                await _reply_and_track(event, uid, txt)
            if not _telegram_bot:
                await _reply_and_track(event, uid, "❌ Сервис недоступен (нет связи с Telegram ботом).")
                return
            from bot_state import bot_state
            if item_id in bot_state.active_alarms:
                await extend_alarm(item_id, minutes, _telegram_bot, reply_fn)
                return
            if item_id in bot_state.active_maintenances:
                await extend_maintenance(item_id, minutes, _telegram_bot, reply_fn)
                return
            await _reply_and_track(event, uid, f"❌ Событие с ID «{item_id}» не найдено.")
            return

    @dp.message_created()
    async def alarm_main_catch_all(event: MessageCreated):
        """В ALARM_MAIN удаляем любые сообщения не от бота и не от админов (в т.ч. без текста)."""
        if _is_alarm_main(event):
            await _alarm_main_moderate(event)
        return

