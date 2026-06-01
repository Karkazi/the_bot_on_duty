# adapters/max/handlers.py — обработчики сообщений MAX (вызов core)

import re
import logging
import asyncio
from typing import TYPE_CHECKING, Optional

from config import CONFIG, is_max_admin
from utils.bot_time import bot_now_naive
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
    clear_last_bot_message_id)
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
    petlocal_option_keyboard,
    confirmation_keyboard,
    regular_photo_skip_keyboard,
    maintenance_time_method_keyboard,
    create_time_spinner_keyboard_max,
    cal_notify_keyboard,
    stats_period_menu,
)

if TYPE_CHECKING:
    from maxapi.types import MessageCreated

logger = logging.getLogger(__name__)

# Callback payload'ы напоминаний «за 5 минут» — доступны автору события, не только MAX-админам.
_MAX_REMINDER_CALLBACK_PAYLOADS = frozenset({
    "reminder_extend",
    "reminder_stop",
    "reminder_extend_maintenance",
    "reminder_stop_maintenance",
})


def _parse_stats_date_range(text: str):
    """
    Диапазон дат в виде:
    - ДД.ММ.ГГГГ-ДД.ММ.ГГГГ
    - ДД.ММ.ГГГГ — ДД.ММ.ГГГГ
    """
    s = (text or "").strip()
    if not s:
        return None
    s = s.replace("—", "-").replace("–", "-")
    parts = [p.strip() for p in s.split("-") if p.strip()]
    if len(parts) != 2:
        return None
    from datetime import datetime as _dt

    try:
        start = _dt.strptime(parts[0], "%d.%m.%Y").date()
        end = _dt.strptime(parts[1], "%d.%m.%Y").date()
        if end < start:
            start, end = end, start
        return start, end
    except Exception:
        return None


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
    except asyncio.CancelledError:
        raise
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
        except asyncio.CancelledError:
            raise
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
    if attachments == "petlocal_keyboard":
        return petlocal_option_keyboard()
    if attachments == "confirmation_keyboard":
        return confirmation_keyboard()
    if attachments == "regular_photo_keyboard":
        return regular_photo_skip_keyboard()
    if attachments == "maintenance_time_method_keyboard":
        return maintenance_time_method_keyboard()
    if attachments == "cal_notify_keyboard":
        return cal_notify_keyboard()
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
        except asyncio.CancelledError:
            raise
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
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("MAX callback reply не удался: %s", e)


async def _handle_max_reminder_callback(event, uid: int, payload: str) -> None:
    """Кнопки напоминания за 5 минут до конца сбоя/работы (аналог Telegram handlers/manage/reminders)."""
    from bot_state import bot_state

    user_state = bot_state.user_states.get(uid)

    if payload in ("reminder_extend", "reminder_stop"):
        if not user_state or user_state.get("type") != "reminder":
            await _reply_max_callback(event, uid, "❌ Это уведомление устарело.", main_menu())
            return
        alarm_id = user_state["alarm_id"]
        alarm = bot_state.active_alarms.get(alarm_id)
        if not alarm:
            await _reply_max_callback(event, uid, "❌ Сбой уже устранён.", main_menu())
            bot_state.user_states.pop(uid, None)
            return
        if payload == "reminder_stop":
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            ok = await stop_alarm(alarm_id, reply_fn)
            if ok:
                bot_state.user_states.pop(uid, None)
            return
        set_manage_session(uid, "extend", item_id=alarm_id, item_type="alarm")
        bot_state.user_states.pop(uid, None)
        await _reply_max_callback(
            event, uid, f"⏳ На сколько продлить сбой {alarm_id}?", extend_duration_menu(alarm_id, "alarm")
        )
        return

    # maintenance
    if not user_state or user_state.get("type") != "maintenance_reminder":
        await _reply_max_callback(event, uid, "❌ Это уведомление устарело.", main_menu())
        return
    work_id = user_state["work_id"]
    work = bot_state.active_maintenances.get(work_id)
    if not work:
        await _reply_max_callback(event, uid, "❌ Работа уже завершена.", main_menu())
        bot_state.user_states.pop(uid, None)
        return
    if payload == "reminder_stop_maintenance":
        async def reply_fn_m(t: str):
            await _reply_max_callback(event, uid, t, main_menu())
        ok = await stop_maintenance(work_id, reply_fn_m)
        if ok:
            bot_state.user_states.pop(uid, None)
        return
    if payload == "reminder_extend_maintenance":
        set_manage_session(uid, "extend", item_id=work_id, item_type="maintenance")
        bot_state.user_states.pop(uid, None)
        await _reply_max_callback(
            event, uid, f"⏳ На сколько продлить работу {work_id}?", extend_duration_menu(work_id, "maintenance")
        )


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
        value_display = config["format"](current_value, bot_now_naive())
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
    now = bot_now_naive()
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
            attachments=maintenance_time_method_keyboard())
        return

    if payload == "spinner_prev":
        if step_index == 0:
            update_session_data(uid, maintenance_spinner=None)
            set_session(uid, "enter_start_time")
            await event.message.edit(
                text="🚫 Выбор отменён. Введите дату или нажмите Спиннеры.",
                attachments=maintenance_time_method_keyboard())
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


async def _execute_cal_work(event, uid: int) -> None:
    """Записывает работу в Confluence и уведомляет Calendar-admin-ов как о новой записи."""
    from adapters.max.sessions import get_session, clear_session
    from datetime import datetime as _dt
    sess = get_session(uid)
    data = (sess or {}).get("data", {})
    clear_session(uid)

    description = data.get("description", "не указано")
    start_time_raw = data.get("start_time")
    end_time_raw = data.get("end_time")
    unavailable_services = data.get("unavailable_services", "не указано")
    tech_description = data.get("cal_tech_description", description)
    cal_notify = data.get("cal_notify", "Нет")

    if not start_time_raw or not end_time_raw:
        await _reply_max_callback(event, uid, "❌ Ошибка: данные сессии неполны.", main_menu())
        return

    try:
        start_dt = _dt.fromisoformat(start_time_raw)
        end_dt = _dt.fromisoformat(end_time_raw)
    except ValueError:
        await _reply_max_callback(event, uid, "❌ Ошибка разбора времени.", main_menu())
        return

    from services.confluence_service import get_confluence_page_id, append_work_to_confluence_table, _make_work_id
    from domain.constants import DATETIME_FORMAT

    page_id = get_confluence_page_id()
    work_data = {
        "description": description,
        "start_time": start_dt,
        "end_time": end_dt,
        "unavailable_services": unavailable_services,
        "cal_tech_description": tech_description,
        "cal_notify": cal_notify,
        "owner": "Дежурный СА",
    }

    await _reply_max_callback(event, uid, "⏳ Записываю в Confluence...", None)
    ok = await append_work_to_confluence_table(page_id, work_data)
    if not ok:
        await _reply_max_callback(event, uid, "❌ Не удалось записать в Confluence. Проверьте логи.", main_menu())
        return

    start_time_str = start_dt.strftime(DATETIME_FORMAT)
    end_time_str = end_dt.strftime(DATETIME_FORMAT)
    work_id = _make_work_id(description, start_time_str, end_time_str)

    from bot_state import bot_state
    row = {
        "work_id": work_id,
        "description": description,
        "start_time_str": start_time_str,
        "end_time_str": end_time_str,
        "unavailable_services": unavailable_services,
        "owner": "Дежурный СА",
        "notify": cal_notify,
        "start_time": start_dt,
        "end_time": end_dt,
    }
    bot_state.known_maintenances_from_confluence[work_id] = {
        **row,
        "status": "no_notify" if cal_notify.lower() in ("нет", "no", "none", "-") else "pending_decision",
    }
    await bot_state.save_state()

    from services.confluence_calendar_worker import notify_admins_about_work
    await notify_admins_about_work(row)

    await _reply_max_callback(
        event, uid,
        f"✅ Работа добавлена в Confluence (ID: {work_id[:8]}).\n"
        f"Уведомления отправлены администраторам календаря.",
        main_menu())


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
        except asyncio.CancelledError:
            raise
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
            "Выберите действие кнопкой ниже. Справка: /help"
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
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("MAX callback: не удалось отправить ответ (user unknown): %s", e)
            return
        calendar_admin_ids = CONFIG.get("MAX", {}).get("CALENDAR_ADMIN_IDS") or []
        allowed = (
            is_max_admin(uid)
            or (payload.startswith("conf_") and uid in calendar_admin_ids)
            or payload in _MAX_REMINDER_CALLBACK_PAYLOADS
        )
        if not allowed:
            try:
                await event.message.answer(
                    "❌ У вас нет прав для управления ботом из MAX. Обратитесь к администратору."
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("MAX callback: не удалось отправить ответ (no admin): %s", e)
            return
        try:
            await event.answer(notification=None)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("MAX callback: не удалось вызвать event.answer: %s", e)

        # Спиннеры времени: не удаляем сообщение, только редактируем
        if payload.startswith("spinner_"):
            await _handle_max_spinner_callback(event, uid, payload)
            return

        # Удаляем сообщение бота с кнопкой — в чате остаётся только следующий ответ
        try:
            await event.message.delete()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("MAX: не удалось удалить сообщение с кнопкой: %s", e)

        if payload in _MAX_REMINDER_CALLBACK_PAYLOADS:
            await _handle_max_reminder_callback(event, uid, payload)
            return

        # Старт спиннеров времени (после "Спиннеры" на шаге enter_start_time)
        if payload == "maint_time_spinners":
            sess = get_session(uid)
            if sess and sess.get("step") == "enter_start_time" and (sess.get("data") or {}).get("type") in ("maintenance", "cal_work"):
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
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning("MAX spinner start: %s", e)
                return

        if payload == "maint_time_manual":
            sess = get_session(uid)
            if sess and sess.get("step") == "enter_start_time" and (sess.get("data") or {}).get("type") in ("maintenance", "cal_work"):
                await _reply_max_callback(
                    event, uid,
                    "⏰ Введите дату и время начала:\n"
                    "02.02.2026 14:00 или через 1 час, завтра 10:00",
                    back_only())
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

        if payload == "cmd_stats":
            if not is_max_admin(uid):
                await _reply_max_callback(event, uid, "❌ Команда доступна только админам.", main_menu())
                return
            clear_session(uid)
            set_manage_session(uid, "stats_period")
            await _reply_max_callback(event, uid, "📊 Выберите период:", stats_period_menu())
            return

        if payload == "cmd_calendar":
            from services.calendar_digest_service import get_today_calendar_digest_text
            text = await get_today_calendar_digest_text()
            await _reply_max_callback(event, uid, text, main_menu())
            return

        if payload == "cmd_events":
            alarms_text, _ = get_active_events_text("alarms", 0, html=False)
            works_text, _ = get_active_events_text("maintenances", 0, html=False)
            await _reply_max_callback(event, uid, alarms_text + "\n\n" + works_text, event_list_menu())
            return

        # Статистика: быстрые периоды / кастом
        if payload in ("stats_today", "stats_7d", "stats_30d", "stats_custom"):
            if not is_max_admin(uid):
                await _reply_max_callback(event, uid, "❌ Команда доступна только админам.", main_menu())
                return
            if payload == "stats_custom":
                set_manage_session(uid, "stats_custom_wait")
                await _reply_max_callback(
                    event,
                    uid,
                    "✏️ Введите диапазон дат: ДД.ММ.ГГГГ-ДД.ММ.ГГГГ",
                    main_menu(),
                )
                return

            from datetime import timedelta as _td
            from services.alarm_history_service import build_alarm_stats_report

            today = bot_now_naive().date()
            if payload == "stats_today":
                start = end = today
            elif payload == "stats_7d":
                start = today - _td(days=6)
                end = today
            else:
                start = today - _td(days=29)
                end = today
            report = build_alarm_stats_report(start=start, end=end)
            clear_manage_session(uid)
            await _reply_max_callback(event, uid, report, main_menu())
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

        # Запрос по новой работе из Confluence: Не информировать
        if payload.startswith("conf_skip_"):
            work_id = payload.replace("conf_skip_", "", 1)
            entry = bot_state.known_maintenances_from_confluence.get(work_id)
            if entry is not None:
                entry["status"] = "skipped_by_admin"
                await bot_state.save_state()
                await _reply_max_callback(event, uid, "Оповещение по этим работам отменено.", main_menu())
            else:
                await _reply_max_callback(event, uid, "Запрос устарел или уже обработан.", main_menu())
            return

        # Запрос по новой работе из Confluence: Информировать
        if payload.startswith("conf_notify_"):
            work_id = payload.replace("conf_notify_", "", 1)
            entry = bot_state.known_maintenances_from_confluence.get(work_id)
            if entry is None or entry.get("status") not in ("pending_decision"):
                await _reply_max_callback(event, uid, "Запрос устарел или уже обработан.", main_menu())
                return
            try:
                from core.creation import create_maintenance
                start_time = entry.get("start_time")
                end_time = entry.get("end_time")
                if start_time is None or end_time is None:
                    await _reply_max_callback(event, uid, "Ошибка данных работы.", main_menu())
                    return
                # Не трогаем работы, где окончание уже прошло
                from datetime import datetime as _dt
                if end_time <= bot_now_naive():
                    entry["status"] = "expired"
                    await bot_state.save_state()
                    await _reply_max_callback(event, uid, "Работы уже завершились — оповещение не отправляем.", main_menu())
                    return
                # Решение встречи: при «Информировать» из календаря — всегда MAX + Петлокал
                data = {
                    "description": entry.get("description", "не указано"),
                    "start_time": start_time.isoformat() if hasattr(start_time, "isoformat") else start_time,
                    "end_time": end_time.isoformat() if hasattr(end_time, "isoformat") else end_time,
                    "unavailable_services": entry.get("unavailable_services", "не указано"),
                    "send_to_max": True,
                    "publish_petlocal": True,
                }
                async def _reply_fn(t: str, attachments=None):
                    await _reply_max_callback(event, uid, t, attachments or main_menu())
                ok = await create_maintenance(data, _reply_fn, uid, author_messenger="max")
                if ok:
                    entry["status"] = "notified"
                    await bot_state.save_state()
                    await _reply_max_callback(event, uid, "Оповещения отправлены: MAX, Петлокал", main_menu())
                else:
                    await _reply_max_callback(event, uid, "Не удалось оповестить. См. логи.", main_menu())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("CONF_MAINT conf_notify: %s", e)
                await _reply_max_callback(event, uid, "Ошибка при отправке оповещений. См. логи.", main_menu())
            return

        # Добавить в календарь работ: выбор каналов оповещения
        if payload in ("cal_notify_none", "cal_notify_petlocal", "cal_notify_messengers", "cal_notify_both"):
            sess = get_session(uid)
            if not (sess and sess.get("step") == "select_cal_notify" and (sess.get("data") or {}).get("type") == "cal_work"):
                await _reply_max_callback(event, uid, "Сессия устарела. Начните заново.", main_menu())
                return
            notify_map = {
                "cal_notify_none": "Нет",
                "cal_notify_petlocal": "Петлокал",
                "cal_notify_messengers": "МАХ",
                "cal_notify_both": "Петлокал+МАХ",
            }
            cal_notify = notify_map[payload]
            update_session_data(uid, cal_notify=cal_notify)
            set_session(uid, "cal_confirm")
            data = get_session(uid).get("data", {})
            from datetime import datetime as _dt
            def _fmt(iso: str) -> str:
                try:
                    return _dt.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
                except ValueError:
                    return iso
            summary = (
                f"📅 Проверьте данные перед добавлением в календарь:\n\n"
                f"• Объект работ: {data.get('description', '—')}\n"
                f"• Начало: {_fmt(data.get('start_time', ''))}\n"
                f"• Окончание: {_fmt(data.get('end_time', ''))}\n"
                f"• Недоступно: {data.get('unavailable_services', '—')}\n"
                f"• Описание для тех. специалистов: {data.get('cal_tech_description', '—')}\n"
                f"• Оповещения: {cal_notify}\n\n"
                f"Добавить запись в Confluence?"
            )
            await _reply_max_callback(event, uid, summary, confirmation_keyboard())
            return

        # Добавить в календарь работ: подтверждение записи
        if payload == "confirm_send":
            sess = get_session(uid)
            if sess and (sess.get("data") or {}).get("type") == "cal_work" and sess.get("step") == "cal_confirm":
                await _execute_cal_work(event, uid)
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
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await stop_alarm(item_id, reply_fn)
            clear_manage_session(uid)
            return
        if payload.startswith("action_stop_m_"):
            item_id = payload.replace("action_stop_m_", "", 1)
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await stop_maintenance(item_id, reply_fn)
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
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await extend_alarm(item_id, 30, reply_fn)
            clear_manage_session(uid)
            return
        if payload.startswith("extend_60_a_"):
            item_id = payload.replace("extend_60_a_", "", 1)
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await extend_alarm(item_id, 60, reply_fn)
            clear_manage_session(uid)
            return
        if payload.startswith("extend_30_m_"):
            item_id = payload.replace("extend_30_m_", "", 1)
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await extend_maintenance(item_id, 30, reply_fn)
            clear_manage_session(uid)
            return
        if payload.startswith("extend_60_m_"):
            item_id = payload.replace("extend_60_m_", "", 1)
            async def reply_fn(t: str):
                await _reply_max_callback(event, uid, t, main_menu())
            await extend_maintenance(item_id, 60, reply_fn)
            clear_manage_session(uid)
            return
        if payload.startswith("extend_custom_a_"):
            item_id = payload.replace("extend_custom_a_", "", 1)
            set_manage_session(uid, "extend_custom_minutes", item_id=item_id, item_type="alarm")
            await _reply_max_callback(
                event,
                uid,
                f"🕒 На сколько минут продлить сбой {item_id}?\n"
                "Введите число от 1 до 10080 (например: 90).",
                back_only())
            return
        if payload.startswith("extend_custom_m_"):
            item_id = payload.replace("extend_custom_m_", "", 1)
            set_manage_session(uid, "extend_custom_minutes", item_id=item_id, item_type="maintenance")
            await _reply_max_callback(
                event,
                uid,
                f"🕒 На сколько минут продлить работу {item_id}?\n"
                "Введите число от 1 до 10080 (например: 90).",
                back_only())
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
            await handle_create_message(event, reply_fn, uid, num)
            return

        if payload == "msg_type_cal_work":
            set_session(uid, "enter_description", {"type": "cal_work"})
            await _reply_max_callback(event, uid, "📅 Опишите работы (объект работ, или «отмена»):", back_only())
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
                from datetime import timedelta
                from domain.constants import DATETIME_FORMAT
                if payload == "jira_yes":
                    update_session_data(uid, create_jira=True)
                    now = bot_now_naive()
                    fix_time = now + timedelta(hours=1)
                    update_session_data(uid, fix_time=fix_time.isoformat())
                    set_session(uid, "select_petlocal")
                    await _reply_max_callback(
                        event, uid,
                        f"✅ Jira будет создана. Исправим до: {fix_time.strftime(DATETIME_FORMAT)}.\n📢 Публиковать на Петлокале?",
                        petlocal_option_keyboard())
                else:
                    from datetime import timedelta
                    from domain.constants import DATETIME_FORMAT
                    update_session_data(uid, create_jira=False)
                    now = bot_now_naive()
                    fix_time = now + timedelta(hours=1)
                    update_session_data(uid, fix_time=fix_time.isoformat())
                    set_session(uid, "select_petlocal")
                    await _reply_max_callback(
                        event, uid,
                        f"Исправим до: {fix_time.strftime(DATETIME_FORMAT)}.\n📢 Публиковать на Петлокале?",
                        petlocal_option_keyboard(),
                    )
                return

        # Выбор сервиса при заведении сбоя (инлайн-кнопки)
        if payload.startswith("svc_"):
            from config import PROBLEM_SERVICES
            from domain.constants import PROBLEM_SERVICE_OTHER
            try:
                idx = int(payload.replace("svc_", "", 1))
                if 0 <= idx < len(PROBLEM_SERVICES):
                    service = PROBLEM_SERVICES[idx]
                    update_session_data(uid, service=service, service_other_spec=None)
                    if service == PROBLEM_SERVICE_OTHER:
                        set_session(uid, "enter_service_other_spec")
                        await _reply_max_callback(
                            event, uid,
                            "✏️ Уточните, какой это сервис (поле «Другое»). Напишите текст сообщением.")
                        return
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
                await _execute_confirmation(uid, _confirm_reply)
                return

        try:
            await _reply_max_callback(event, uid, "Неизвестная команда.", main_menu())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("MAX: не удалось отправить ответ «Неизвестная команда»: %s", e)

    @dp.message_created()
    async def message_created_router(event: MessageCreated):
        if _is_alarm_main(event):
            await _alarm_main_moderate(event)
            return
        if _is_direct_chat(event):
            await _handle_direct_chat_message(event)
            return

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

        # Сценарий "Управлять" -> "Продлить" -> "Другое время"
        manage_sess = get_manage_session(uid) or {}
        if manage_sess.get("step") == "stats_custom_wait":
            if not is_max_admin(uid):
                clear_manage_session(uid)
                await _reply_and_track(event, uid, "❌ Команда доступна только админам.")
                return
            parsed = _parse_stats_date_range(text)
            if not parsed:
                await _reply_and_track(event, uid, "❌ Не понял диапазон. Формат: ДД.ММ.ГГГГ-ДД.ММ.ГГГГ")
                return
            from services.alarm_history_service import build_alarm_stats_report

            start, end = parsed
            report = build_alarm_stats_report(start=start, end=end)
            clear_manage_session(uid)
            await _reply_and_track(event, uid, report, main_menu())
            return

        if manage_sess.get("step") == "extend_custom_minutes":
            item_id = (manage_sess.get("item_id") or "").strip()
            item_type = (manage_sess.get("item_type") or "").strip()
            if not item_id or item_type not in ("alarm", "maintenance"):
                clear_manage_session(uid)
                await _reply_and_track(event, uid, "❌ Сессия продления устарела. Начните заново.")
                return
            if text_lower in ("отмена", "назад", "back", "cancel"):
                clear_manage_session(uid)
                await _reply_and_track(event, uid, "🚫 Продление отменено.")
                return
            try:
                minutes = int(text_lower)
            except ValueError:
                await _reply_and_track(event, uid, "❌ Введите целое число минут, например: 90")
                return
            if minutes <= 0 or minutes > 10080:
                await _reply_and_track(event, uid, "❌ Укажите минуты от 1 до 10080 (неделя).")
                return

            async def reply_fn(txt):
                await _reply_and_track(event, uid, txt)

            if item_type == "alarm":
                await extend_alarm(item_id, minutes, reply_fn)
            else:
                await extend_maintenance(item_id, minutes, reply_fn)
            clear_manage_session(uid)
            return

        # Сценарий «Сообщить»: сессия или команда «сообщить» (удаляем предыдущее сообщение бота, отправляем новое)
        async def _reply_fn(t: str, attachments=None):
            await _reply_and_track(event, uid, t, attachments)
        consumed = await handle_create_message(
            event, _reply_fn, uid, text or "")
        if consumed:
            return
        if not text:
            return

        # Список событий: текущие, список, события, сбои, работы
        if text_lower in ("календарь", "📅 календарь"):
            from services.calendar_digest_service import get_today_calendar_digest_text
            text_cal = await get_today_calendar_digest_text()
            await _reply_and_track(event, uid, text_cal, main_menu())
            return

        if text_lower in ("статистика", "📊 статистика", "stats"):
            if not is_max_admin(uid):
                await _reply_and_track(event, uid, "❌ Команда доступна только админам.", main_menu())
                return
            clear_session(uid)
            set_manage_session(uid, "stats_period")
            await _reply_and_track(event, uid, "📊 Выберите период:", stats_period_menu())
            return

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
            from bot_state import bot_state
            if item_id in bot_state.active_alarms:
                await stop_alarm(item_id, reply_fn)
                return
            if item_id in bot_state.active_maintenances:
                await stop_maintenance(item_id, reply_fn)
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
            from bot_state import bot_state
            if item_id in bot_state.active_alarms:
                await extend_alarm(item_id, minutes, reply_fn)
                return
            if item_id in bot_state.active_maintenances:
                await extend_maintenance(item_id, minutes, reply_fn)
                return
            await _reply_and_track(event, uid, f"❌ Событие с ID «{item_id}» не найдено.")
            return


