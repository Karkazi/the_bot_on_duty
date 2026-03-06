"""
Обработчики для создания аварий.
Содержит логику выбора типа сообщения, ввода описания, выбора сервиса и опций Jira/SCM.
"""
import logging
from datetime import datetime as dt, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from keyboards import (
    create_cancel_keyboard,
    create_main_keyboard,
    create_message_type_keyboard,
    create_service_keyboard,
    create_jira_option_keyboard,
    create_scm_option_keyboard,
    create_confirmation_keyboard,
)
from keyboards.alarm import create_petlocal_option_keyboard
from utils.helpers import is_admin
from utils.validation import validate_description, sanitize_html
from utils.callback_validator import validate_callback, validate_callback_in
from utils.telegram_retry import safe_send_message, safe_edit_message
from domain.states import NewMessageStates
from domain.constants import PROBLEM_LEVEL_POTENTIAL
from config import PROBLEM_LEVELS, PROBLEM_SERVICES

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("new_message"))
@router.message(F.text == "📢 Сообщить")
async def new_message_start(message: Message, state: FSMContext):
    """
    Обработчик начала создания нового сообщения.
    
    Позволяет выбрать тип сообщения: авария, регламентная работа или обычное сообщение.
    Требует прав администратора.
    """
    user_id = message.from_user.id
    logger.info(f"[{user_id}] Пользователь начал создание нового сообщения")
    if not is_admin(user_id):
        logger.warning(f"[{user_id}] Попытка начать создание сообщения без прав администратора")
        await message.answer(
            "❌ У вас нет прав для выполнения этой команды.\n"
            "Обратитесь к администратору для получения доступа.",
            parse_mode='HTML'
        )
        return
    await state.clear()
    logger.info(f"[{user_id}] Состояние очищено")
    await message.answer("Выберите тип сообщения:", reply_markup=create_message_type_keyboard())
    await state.set_state(NewMessageStates.SELECTING_TYPE)


@router.callback_query(F.data.startswith("message_type_"))
async def handle_message_type(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора типа сообщения"""
    if not await validate_callback(call, "message_type_"):
        return
    
    msg_type = call.data.split("_")[-1]  # 'alarm', 'maintenance', 'regular'
    
    # Валидация типа сообщения
    valid_types = ["alarm", "maintenance", "regular"]
    if msg_type not in valid_types:
        logger.warning(f"[{call.from_user.id}] Неизвестный тип сообщения: {msg_type}")
        await call.answer("❌ Неизвестный тип сообщения", show_alert=True)
        return
    
    logger.info(f"[{call.from_user.id}] Выбран тип сообщения: {msg_type}")
    if msg_type == "alarm":
        await state.set_state(NewMessageStates.ENTER_DESCRIPTION)
        await call.message.answer("✏️ Опишите проблему:", reply_markup=create_cancel_keyboard())
    elif msg_type == "maintenance":
        await state.set_state(NewMessageStates.ENTER_DESCRIPTION)
        await call.message.answer("🔧 Опишите работы:", reply_markup=create_cancel_keyboard())
    elif msg_type == "regular":
        await state.set_state(NewMessageStates.ENTER_MESSAGE_TEXT)
        await call.message.answer("💬 Введите текст сообщения:", reply_markup=create_cancel_keyboard())
    await state.update_data(type=msg_type)
    await call.answer()


@router.message(NewMessageStates.ENTER_DESCRIPTION)
async def enter_description(message: Message, state: FSMContext):
    """
    Обработчик ввода описания проблемы или работ.
    
    Валидирует описание и переходит к следующему шагу в зависимости от типа сообщения.
    """
    description = message.text.strip()
    user_id = message.from_user.id
    logger.info(f"[{user_id}] Введено описание: {description[:30]}...")
    if description == "❌ Отмена":
        logger.info(f"[{user_id}] Действие отменено пользователем")
        await state.clear()
        await message.answer("🚫 Действие отменено", reply_markup=create_main_keyboard())
        return
    
    # Валидация описания
    is_valid, error_msg = validate_description(description)
    if not is_valid:
        await message.answer(
            f"{error_msg}\n\n"
            "💡 Попробуйте ввести описание заново.",
            reply_markup=create_cancel_keyboard()
        )
        return
    
    # Санитизация HTML
    description = sanitize_html(description)
    await state.update_data(description=description)
    data = await state.get_data()
    if data["type"] == "alarm":
        # Автоматически устанавливаем уровень (используем константу)
        await state.update_data(level=PROBLEM_LEVEL_POTENTIAL)
        await state.set_state(NewMessageStates.ENTER_SERVICE)
        # Используем безопасную отправку с retry для сетевых ошибок
        result = await safe_send_message(
            message,
            "Выберите затронутый сервис:",
            reply_markup=create_service_keyboard()
        )
        if result is None:
            logger.warning(f"[{user_id}] Не удалось отправить сообщение через safe_send_message, пробуем обычный метод")
            try:
                await message.answer("Выберите затронутый сервис:", reply_markup=create_service_keyboard())
            except Exception as e:
                logger.error(f"[{user_id}] Критическая ошибка при отправке сообщения: {e}", exc_info=True)
                await message.answer(
                    "⚠️ Произошла ошибка при отправке сообщения. Попробуйте начать заново.",
                    reply_markup=create_main_keyboard(user_id)
                )
                await state.clear()
    elif data["type"] == "maintenance":
        logger.info(f"[{user_id}] Запрошен выбор способа ввода времени работ")
        # Предлагаем выбор способа ввода времени
        from keyboards import create_maintenance_time_selection_keyboard
        await message.answer(
            "⏰ Выберите способ ввода времени работ:",
            reply_markup=create_maintenance_time_selection_keyboard()
        )
        await state.set_state(NewMessageStates.ENTER_DESCRIPTION)  # Остаемся в состоянии для обработки выбора способа


@router.callback_query(F.data.startswith("lvl_"))
async def process_level(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора уровня проблемы"""
    user_id = callback.from_user.id
    
    if not await validate_callback(callback, "lvl_"):
        return
    
    try:
        level_index = int(callback.data.replace("lvl_", ""))
        if level_index < 0 or level_index >= len(PROBLEM_LEVELS):
            logger.warning(f"[{user_id}] Некорректный индекс уровня: {level_index}")
            await callback.answer("❌ Неизвестный уровень", show_alert=True)
            return
        level = PROBLEM_LEVELS[level_index]
    except (ValueError, IndexError) as e:
        logger.error(f"[{user_id}] Ошибка парсинга уровня: {e}")
        await callback.answer("❌ Ошибка обработки", show_alert=True)
        return
    await state.update_data(level=level)
    await state.set_state(NewMessageStates.ENTER_SERVICE)
    result = await safe_edit_message(
        callback.message,
        "Выберите затронутый сервис:",
        reply_markup=create_service_keyboard()
    )
    if result is None:
        logger.warning(f"[{user_id}] Не удалось отредактировать сообщение, пробуем отправить новое")
        try:
            await callback.message.answer(
                "Выберите затронутый сервис:",
                reply_markup=create_service_keyboard()
            )
        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка при отправке сообщения: {e}", exc_info=True)


@router.callback_query(F.data.startswith("svc_"))
async def process_service(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора сервиса"""
    user_id = callback.from_user.id
    
    if not await validate_callback(callback, "svc_"):
        return
    
    try:
        service_index = int(callback.data.replace("svc_", ""))
        if service_index < 0 or service_index >= len(PROBLEM_SERVICES):
            logger.warning(f"[{user_id}] Некорректный индекс сервиса: {service_index}")
            await callback.answer("❌ Неизвестный сервис", show_alert=True)
            return
        service = PROBLEM_SERVICES[service_index]
    except (ValueError, IndexError) as e:
        logger.error(f"[{user_id}] Ошибка парсинга сервиса: {e}")
        await callback.answer("❌ Ошибка обработки", show_alert=True)
        return
    logger.info(f"[{user_id}] Выбран сервис: {service}")
    await state.update_data(service=service)
    
    # Переход к выбору создания задачи в Jira
    await state.set_state(NewMessageStates.SELECT_JIRA_OPTION)
    await callback.message.edit_text(
        "📋 Создать задачу в Jira?",
        reply_markup=create_jira_option_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.in_(["jira_create", "jira_skip"]))
async def handle_jira_option(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора создания задачи в Jira"""
    user_id = callback.from_user.id
    
    if not await validate_callback_in(callback, ["jira_create", "jira_skip"]):
        return
    
    create_jira = callback.data == "jira_create"
    logger.info(f"[{user_id}] Выбран вариант создания задачи в Jira: {create_jira}")
    await state.update_data(create_jira=create_jira)
    
    # Если выбрано "Без задачи в Jira", спрашиваем про SCM
    if not create_jira:
        await state.set_state(NewMessageStates.SELECT_SCM_OPTION)
        await callback.message.edit_text(
            "📋 Завести тему в канале SCM?",
            reply_markup=create_scm_option_keyboard()
        )
        await callback.answer()
        return
    
    # Если выбрано создание задачи в Jira, продолжаем как раньше
    # Автоматически устанавливаем время +1 час от текущего
    now = dt.now()
    fix_time = now + timedelta(hours=1)
    await state.update_data(fix_time=fix_time.isoformat())
    
    # Показываем предварительный просмотр
    data = await state.get_data()
    description = data.get("description", "")
    service = data["service"]
    jira_option = "✅ Создать задачу в Jira" if create_jira else "❌ Без задачи в Jira"
    from domain.constants import DATETIME_FORMAT
    preview_text = (
        "📄 <b>Предварительный просмотр:</b>\n"
        f"🚨 <b>Технический сбой</b>\n"
        f"• <b>Описание:</b> {description}\n"
        f"• <b>Сервис:</b> {service}\n"
        f"• <b>Jira:</b> {jira_option}\n"
        f"• <b>Исправим до:</b> {fix_time.strftime(DATETIME_FORMAT)}"
    )
    await state.update_data(preview_text=preview_text)

    # ИСПРАВЛЕНИЕ: Используем новое сообщение вместо редактирования
    logger.info(f"[{user_id}] Отправляем вопрос о публикации на Петлокале")
    result = await safe_edit_message(
        callback.message,
        "📢 <b>Публикуем на Петлокале?</b>",
        parse_mode='HTML',
        reply_markup=create_petlocal_option_keyboard()
    )
    if result is None:
        logger.warning(f"[{user_id}] Не удалось отредактировать сообщение, пробуем отправить новое")
        try:
            await callback.message.answer(
                "📢 <b>Публикуем на Петлокале?</b>",
                parse_mode='HTML',
                reply_markup=create_petlocal_option_keyboard()
            )
        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка при отправке вопроса: {e}", exc_info=True)
    await state.set_state(NewMessageStates.SELECT_PETLOCAL_OPTION)
    await callback.answer()


@router.callback_query(F.data.in_(["petlocal_publish", "petlocal_skip"]))
async def handle_petlocal_option(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора публикации на Петлокале"""
    user_id = callback.from_user.id
    
    if not await validate_callback_in(callback, ["petlocal_publish", "petlocal_skip"]):
        return
    
    publish_petlocal = callback.data == "petlocal_publish"
    logger.info(f"[{user_id}] Выбран вариант публикации на Петлокале: {publish_petlocal}")
    await state.update_data(publish_petlocal=publish_petlocal)
    
    # Получаем данные для предварительного просмотра
    data = await state.get_data()
    msg_type = data.get("type")
    preview_text = data.get("preview_text", "")
    
    # Добавляем информацию о публикации на Петлокале в предпросмотр
    petlocal_option = "✅ Публикуем на Петлокале" if publish_petlocal else "❌ Не публикуем на Петлокале"
    if preview_text:
        preview_text += f"\n• <b>Петлокал:</b> {petlocal_option}"
    else:
        # Если preview_text нет, создаем базовый
        preview_text = f"📄 <b>Предварительный просмотр:</b>\n• <b>Петлокал:</b> {petlocal_option}"
    
    await state.update_data(preview_text=preview_text)
    
    # Показываем предварительный просмотр с кнопкой подтверждения
    result = await safe_edit_message(
        callback.message,
        preview_text,
        parse_mode='HTML',
        reply_markup=create_confirmation_keyboard()
    )
    if result is None:
        logger.warning(f"[{user_id}] Не удалось отредактировать сообщение, пробуем отправить новое")
        try:
            await callback.message.answer(
                preview_text,
                parse_mode='HTML',
                reply_markup=create_confirmation_keyboard()
            )
        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка при отправке предпросмотра: {e}", exc_info=True)
    await state.set_state(NewMessageStates.CONFIRMATION)
    await callback.answer()


@router.callback_query(F.data.in_(["scm_create", "scm_skip"]))
async def handle_scm_option(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора создания темы в SCM канале"""
    user_id = callback.from_user.id
    
    if not await validate_callback_in(callback, ["scm_create", "scm_skip"]):
        return
    
    create_scm = callback.data == "scm_create"
    logger.info(f"[{user_id}] Выбран вариант создания темы в SCM: {create_scm}")
    await state.update_data(create_scm=create_scm)
    
    # Автоматически устанавливаем время +1 час от текущего
    now = dt.now()
    fix_time = now + timedelta(hours=1)
    await state.update_data(fix_time=fix_time.isoformat())
    
    # Показываем предварительный просмотр
    data = await state.get_data()
    description = data.get("description", "")
    service = data["service"]
    scm_option = "✅ Завести в SCM" if create_scm else "❌ Не заводить в SCM"
    from domain.constants import DATETIME_FORMAT
    preview_text = (
        "📄 <b>Предварительный просмотр:</b>\n"
        f"🚨 <b>Технический сбой</b>\n"
        f"• <b>Описание:</b> {description}\n"
        f"• <b>Сервис:</b> {service}\n"
        f"• <b>SCM:</b> {scm_option}\n"
        f"• <b>Исправим до:</b> {fix_time.strftime(DATETIME_FORMAT)}"
    )
    await state.update_data(preview_text=preview_text)
    
    result = await safe_edit_message(
        callback.message,
        "📢 <b>Публикуем на Петлокале?</b>",
        parse_mode='HTML',
        reply_markup=create_petlocal_option_keyboard()
    )
    if result is None:
        logger.warning(f"[{user_id}] Не удалось отредактировать сообщение, пробуем отправить новое")
        try:
            await callback.message.answer(
                "📢 <b>Публикуем на Петлокале?</b>",
                parse_mode='HTML',
                reply_markup=create_petlocal_option_keyboard()
            )
        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка при отправке вопроса: {e}", exc_info=True)
    await state.set_state(NewMessageStates.SELECT_PETLOCAL_OPTION)
    await callback.answer()
