# adapters/max/create_flow.py — сценарий «Сообщить» в MAX (сбой / работа / обычное)

import logging
from datetime import datetime as dt, timedelta

from config import PROBLEM_SERVICES
from domain.constants import DATETIME_FORMAT
from utils.validation import (
    validate_description,
    validate_message_text,
    validate_datetime_format,
    sanitize_html,
)
from utils.datetime_utils import parse_flexible_datetime
from adapters.max.sessions import get_session, set_session, update_session_data, clear_session
from core.creation import create_alarm, create_maintenance, send_regular_message

logger = logging.getLogger(__name__)


def _chat_id_from_event(event) -> str | None:
    """Извлекает chat_id из события MAX (без зависимостей на handlers.py)."""
    try:
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
    except Exception:
        return None
    return None


def _message_mid_from_event(event) -> str | None:
    """Извлекает mid/id сообщения MAX для fallback через get_messages."""
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
    except Exception:
        return None
    return None


def _services_list_plain() -> str:
    lines = []
    for i, name in enumerate(PROBLEM_SERVICES, 1):
        lines.append(f"{i}. {name}")
    return "\n".join(lines)


async def handle_create_message(event, reply_fn, user_id: int, text: str, telegram_bot=None) -> bool:
    """
    Обрабатывает сообщение в контексте сценария «Сообщить».
    Возвращает True если сообщение обработано (сессия была или начата).
    """
    text = (text or "").strip()
    text_lower = text.lower()

    # Отмена в любой момент
    if text_lower in ("отмена", "отменить", "cancel"):
        session = get_session(user_id)
        if session:
            clear_session(user_id)
            await reply_fn("🚫 Действие отменено.")
        return bool(session)

    session = get_session(user_id)
    if not session:
        if text_lower not in ("сообщить", "сообщить о сбое", "новое сообщение", "1", "2", "3"):
            return False
        if text_lower in ("сообщить", "сообщить о сбое", "новое сообщение"):
            set_session(user_id, "select_type", {"type": None})
            await reply_fn(
                "📢 Выберите тип сообщения:\n"
                "1 — сбой\n2 — работа\n3 — обычное сообщение\n\nНапишите цифру или «отмена»."
            )
            return True
        return False

    step = session.get("step", "")
    data = session.get("data", {})

    # select_type: 1/2/3 или сбой/работа/обычное
    if step == "select_type":
        if text.strip() == "1" or text_lower in ("сбой", "авария"):
            update_session_data(user_id, type="alarm")
            set_session(user_id, "enter_description")
            await reply_fn("✏️ Опишите проблему (или «отмена»):")
            return True
        if text.strip() == "2" or text_lower in ("работа", "работы"):
            update_session_data(user_id, type="maintenance")
            set_session(user_id, "enter_description")
            await reply_fn("🔧 Опишите работы (или «отмена»):")
            return True
        if text.strip() == "3" or text_lower in ("обычное", "сообщение"):
            update_session_data(user_id, type="regular")
            set_session(user_id, "enter_message_text")
            await reply_fn("💬 Введите текст сообщения (или «отмена»):")
            return True
        await reply_fn("Введите 1, 2 или 3.")
        return True

    msg_type = data.get("type")

    # --- Сбой ---
    if step == "enter_description" and msg_type == "alarm":
        ok, err = validate_description(text)
        if not ok:
            await reply_fn(err or "Неверное описание.")
            return True
        update_session_data(user_id, description=sanitize_html(text))
        set_session(user_id, "enter_service")
        # Второй аргумент "service_keyboard" — для MAX показываем инлайн-кнопки; в TG игнорируется
        await reply_fn("Выберите затронутый сервис:", "service_keyboard")
        return True

    if step == "enter_service" and msg_type == "alarm":
        try:
            idx = int(text)
            if 1 <= idx <= len(PROBLEM_SERVICES):
                service = PROBLEM_SERVICES[idx - 1]
                update_session_data(user_id, service=service)
                set_session(user_id, "select_jira")
                # В MAX показываем кнопки «Да» / «Нет»
                await reply_fn("📋 Создать задачу в Jira?", "jira_keyboard")
                return True
        except ValueError:
            pass
        await reply_fn(f"Введите номер от 1 до {len(PROBLEM_SERVICES)}.")
        return True

    if step == "select_jira" and msg_type == "alarm":
        if text_lower in ("да", "yes", "1"):
            update_session_data(user_id, create_jira=True)
            now = dt.now()
            fix_time = now + timedelta(hours=1)
            update_session_data(user_id, fix_time=fix_time.isoformat())
            set_session(user_id, "select_petlocal")
            await reply_fn(
                f"✅ Jira будет создана. Исправим до: {fix_time.strftime(DATETIME_FORMAT)}.\n"
                "📢 Публиковать на Петлокале?",
                "petlocal_keyboard",
            )
            return True
        if text_lower in ("нет", "no", "0"):
            update_session_data(user_id, create_jira=False)
            set_session(user_id, "select_scm")
            # В MAX показываем кнопки «Завести в SCM» / «Не заводить в SCM»
            await reply_fn("📋 Завести тему в канале SCM?", "scm_keyboard")
            return True
        await reply_fn("Напишите да или нет.")
        return True

    if step == "select_scm" and msg_type == "alarm":
        # Обработка текста «да»/«нет» (callback scm_create/scm_skip обрабатывается в handlers)
        if text_lower in ("да", "yes"):
            update_session_data(user_id, create_scm=True)
        else:
            update_session_data(user_id, create_scm=False)
        now = dt.now()
        fix_time = now + timedelta(hours=1)
        update_session_data(user_id, fix_time=fix_time.isoformat())
        set_session(user_id, "select_petlocal")
        await reply_fn(
            f"Исправим до: {fix_time.strftime(DATETIME_FORMAT)}.\n"
            "📢 Публиковать на Петлокале?",
            "petlocal_keyboard",
        )
        return True

    # --- Работа ---
    if step == "enter_description" and msg_type == "maintenance":
        ok, err = validate_description(text)
        if not ok:
            await reply_fn(err or "Неверное описание.")
            return True
        update_session_data(user_id, description=sanitize_html(text))
        set_session(user_id, "enter_start_time")
        await reply_fn(
            "⏰ Время начала. Нажмите «Спиннеры» или напишите дату и время:\n"
            "• Точный формат: 02.02.2026 14:00\n"
            "• Или: через 30 мин, через 1 час, сегодня 14:00, завтра 10:00, 14:00",
            "maintenance_time_method_keyboard",
        )
        return True

    if step == "enter_start_time" and msg_type == "maintenance":
        start_time = parse_flexible_datetime(text, base_time=None, format_str=DATETIME_FORMAT)
        if start_time is None:
            is_valid, err = validate_datetime_format(text, DATETIME_FORMAT)
            if not is_valid:
                await reply_fn(
                    err or "Неверный формат. Примеры: 02.02.2026 14:00, через 1 час, завтра 10:00"
                )
            return True
        update_session_data(user_id, start_time=start_time.isoformat())
        set_session(user_id, "enter_end_time")
        await reply_fn(
            "⏰ Время окончания. Напишите дату и время или, например:\n"
            "• через 1 час (от начала), 02.02.2026 18:00, завтра 12:00"
        )
        return True

    if step == "enter_end_time" and msg_type == "maintenance":
        session_data = get_session(user_id)
        data = session_data.get("data", {})
        start_str = data.get("start_time")
        if not start_str:
            await reply_fn("Ошибка: нет времени начала. Начните заново (напишите «сообщить»).")
            clear_session(user_id)
            return True
        start_time = dt.fromisoformat(start_str)
        # Для окончания «через N час» считаем от начала работ
        end_time = parse_flexible_datetime(text, base_time=start_time, format_str=DATETIME_FORMAT)
        if end_time is None:
            is_valid, err = validate_datetime_format(text, DATETIME_FORMAT)
            if not is_valid:
                await reply_fn(err or "Неверный формат. Пример: 02.02.2026 18:00 или через 1 час")
            return True
        if end_time <= start_time:
            await reply_fn("Время окончания должно быть позже начала.")
            return True
        update_session_data(user_id, end_time=end_time.isoformat())
        set_session(user_id, "enter_unavailable_services")
        await reply_fn("🔌 Что будет недоступно во время работ? (кратко)")
        return True

    if step == "enter_unavailable_services" and msg_type == "maintenance":
        update_session_data(user_id, unavailable_services=text.strip() or "не указано")
        set_session(user_id, "select_petlocal")
        await reply_fn("📢 Публиковать на Петлокале?", "petlocal_keyboard")
        return True

    # --- Обычное сообщение ---
    if step == "enter_message_text" and msg_type == "regular":
        ok, err = validate_message_text(text)
        if not ok:
            await reply_fn(err or "Неверный текст.")
            return True
        update_session_data(user_id, message_text=text.strip())
        set_session(user_id, "enter_message_photo")
        await reply_fn("📷 Приложить картинку? Отправьте фото или нажмите «Пропустить».", "regular_photo_keyboard")
        return True

    if step == "enter_message_photo" and msg_type == "regular":
        # В MAX принимаем картинку из вложения сообщения.
        if text_lower in ("пропустить", "skip", "нет", "no"):
            set_session(user_id, "select_petlocal")
            await reply_fn("📢 Публиковать на Петлокале?", "petlocal_keyboard")
            return True

        image_url = None
        try:
            msg = getattr(event, "message", event)
            from services.max_media import extract_attachments_from_max_message

            for att in extract_attachments_from_max_message(msg):
                url = (att.get("url") or "").strip()
                if att.get("type") in ("image", "photo") and url.startswith("http"):
                    image_url = url
                    break
        except Exception as e:
            logger.debug("MAX regular photo: не удалось извлечь вложение: %s", e)

        # Fallback: в MessageCreated может не быть URL вложения (только token).
        # Тогда пробуем получить это же сообщение из истории чата.
        if not image_url:
            try:
                from services.max_service import MaxService

                cid = _chat_id_from_event(event)
                mid = _message_mid_from_event(event)
                if cid:
                    svc = MaxService()
                    if svc.is_configured():
                        history = await svc.get_messages(cid, count=20) or []
                        picked = None
                        if mid:
                            for m in history:
                                if str(m.get("mid") or "") == mid:
                                    picked = m
                                    break
                        if picked is None and history:
                            picked = history[0]
                        if picked:
                            for att in picked.get("attachments") or []:
                                url = (att.get("url") or "").strip()
                                if att.get("type") in ("image", "photo") and url.startswith("http"):
                                    image_url = url
                                    logger.info("MAX regular photo: вложение восстановлено через get_messages (mid=%s)", mid)
                                    break
            except Exception as e:
                logger.debug("MAX regular photo: fallback get_messages не сработал: %s", e)

        if image_url:
            update_session_data(user_id, photo_url_from_max=image_url)
            set_session(user_id, "select_petlocal")
            await reply_fn("✅ Картинка прикреплена.\n📢 Публиковать на Петлокале?", "petlocal_keyboard")
            return True

        await reply_fn("📷 Пришлите картинку сообщением или нажмите «Пропустить».", "regular_photo_keyboard")
        return True

    # --- Петлокал (общий) ---
    if step == "select_petlocal":
        if text_lower in ("да", "yes"):
            update_session_data(user_id, publish_petlocal=True)
        else:
            update_session_data(user_id, publish_petlocal=False)
        set_session(user_id, "confirmation")
        await reply_fn(
            "Проверьте данные выше. Отправить?",
            "confirmation_keyboard",
        )
        return True

    # --- Подтверждение ---
    if step == "confirmation":
        if text_lower not in ("да", "подтвердить", "yes"):
            await reply_fn("Напишите «да» или «подтвердить» для отправки.")
            return True
        await _execute_confirmation(user_id, reply_fn, telegram_bot)
        return True

    return True


async def _execute_confirmation(user_id: int, reply_fn, telegram_bot) -> None:
    """Выполняет отправку по данным сессии (вызывается из текста или callback в MAX)."""
    if not telegram_bot:
        await reply_fn("❌ Сервис недоступен (нет связи с Telegram ботом).")
        return
    session = get_session(user_id)
    data = (session or {}).get("data", {})
    msg_type = data.get("type")
    try:
        if msg_type == "alarm":
            await create_alarm(data, telegram_bot, reply_fn, user_id)
        elif msg_type == "maintenance":
            await create_maintenance(data, telegram_bot, reply_fn, user_id)
        elif msg_type == "regular":
            await send_regular_message(data, telegram_bot, reply_fn, user_id)
        else:
            await reply_fn("❌ Неизвестный тип сообщения.")
    except Exception as e:
        logger.exception("Ошибка создания из MAX: %s", e)
        await reply_fn("❌ Не удалось отправить. Проверьте логи.")
    clear_session(user_id)
