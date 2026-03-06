# handlers/current_events.py

import logging
from aiogram.filters import Command
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode

from bot_state import bot_state
from keyboards import create_event_list_keyboard, create_refresh_keyboard

logger = logging.getLogger(__name__)
router = Router()

ITEMS_PER_PAGE = 5  # Сколько событий показывать на одной странице


def format_alarms_page(alarms: dict, page: int) -> tuple:
    """
    Форматирует список сбоёв для отображения постранично.
    
    Args:
        alarms: Словарь аварий {alarm_id: alarm_data}
        page: Номер страницы (начиная с 0)
    
    Returns:
        Кортеж (текст сообщения, общее количество страниц)
    """
    alarm_items = list(alarms.items())
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = alarm_items[start:end]

    if not page_items:
        return "🚨 Нет активных сбоёв.", None

    text = "<b>🚨 Активные сбои:</b>\n\n"
    for alarm_id, alarm_info in page_items:
        try:
            fix_time = alarm_info["fix_time"].strftime("%d.%m.%Y %H:%M")
        except Exception as e:
            logger.warning(f"Ошибка форматирования времени сбоя {alarm_id}: {e}")
            fix_time = "неизвестно"
        author = alarm_info.get("user_id", "Неизвестен")
        text += (
            f"• <code>{alarm_id}</code>\n"
            f"  👤 Автор: {author}\n"
            f"  🕒 Исправим до: {fix_time}\n"
            f"  🔧 Проблема: {alarm_info['issue']}\n\n"
        )

    total_pages = (len(alarm_items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    return text, total_pages


def format_maintenances_page(maintenances: dict, page: int) -> tuple:
    """
    Форматирует список регламентных работ для отображения постранично.
    
    Args:
        maintenances: Словарь работ {work_id: work_data}
        page: Номер страницы (начиная с 0)
    
    Returns:
        Кортеж (текст сообщения, общее количество страниц)
    """
    maint_items = list(maintenances.items())
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = maint_items[start:end]

    if not page_items:
        return "🔧 Нет активных работ.", None

    text = "<b>🔧 Активные работы:</b>\n\n"
    for work_id, work_info in page_items:
        try:
            start_time = work_info["start_time"].strftime("%d.%m.%Y %H:%M")
            end_time = work_info["end_time"].strftime("%d.%m.%Y %H:%M")
        except Exception as e:
            logger.warning(f"Ошибка форматирования времени работы {work_id}: {e}")
            start_time = end_time = "неизвестно"
        description = work_info.get("description", "Нет описания")
        author = work_info.get("user_id", "Неизвестен")
        text += (
            f"• <code>{work_id}</code>\n"
            f"  👤 Автор: {author}\n"
            f"  ⏰ Время: {start_time} — {end_time}\n"
            f"  📝 Описание: {description}\n\n"
        )

    total_pages = (len(maint_items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    return text, total_pages


@router.message(Command("alarm_list"))
@router.message(F.text == "📕 Текущие события")
async def show_current_events(message: Message, state: FSMContext):
    user_id = message.from_user.id
    logger.info(f"[{user_id}] Пользователь запросил просмотр текущих событий")

    await state.clear()
    await state.set_data({"page": 0})

    keyboard = create_event_list_keyboard()
    await message.answer("Выберите, что вы хотите посмотреть:", reply_markup=keyboard)


@router.callback_query(lambda call: call.data in ["show_alarms", "show_maintenances"])
async def handle_list_callback(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    choice = call.data
    data = await state.get_data()
    page = data.get("page", 0)

    logger.info(f"[{user_id}] Пользователь выбрал: {choice}, страница: {page}")

    if choice == "show_alarms":
        # Админы и суперадмины видят все сбои, остальные — только свои
        alarms = bot_state.get_user_active_alarms(user_id)
        text, total_pages = format_alarms_page(alarms, page)
        await state.update_data(view="alarms", total_pages=total_pages)

    elif choice == "show_maintenances":
        # Админы и суперадмины видят все работы, остальные — только свои
        maintenances = bot_state.get_user_active_maintenances(user_id)
        text, total_pages = format_maintenances_page(maintenances, page)
        await state.update_data(view="maintenances", total_pages=total_pages)

    else:
        text = "❌ Неизвестная команда"
        total_pages = None

    markup = create_refresh_keyboard(current_page=page, total_pages=total_pages)
    try:
        await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception as e:
        logger.warning(f"[{user_id}] Ошибка при редактировании сообщения: {e}")
        await call.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    await call.answer()


@router.callback_query(F.data == "refresh_selection")
async def refresh_selection(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    logger.info(f"[{user_id}] Пользователь нажал «🔄 Обновить»")
    await call.answer("🔄 Обновляю данные...", show_alert=False)

    data = await state.get_data()
    view = data.get("view", "alarms")
    page = data.get("page", 0)

    if view == "alarms":
        alarms = bot_state.get_user_active_alarms(user_id)
        text, total_pages = format_alarms_page(alarms, page)
    elif view == "maintenances":
        maintenances = bot_state.get_user_active_maintenances(user_id)
        text, total_pages = format_maintenances_page(maintenances, page)
    else:
        text = "❌ Неизвестное состояние"
        total_pages = None

    markup = create_refresh_keyboard(current_page=page, total_pages=total_pages)
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await call.answer("✅ Данные обновлены")


@router.callback_query(F.data == "close_selection")
async def close_selection(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    logger.info(f"[{user_id}] Пользователь нажал «❌ Закрыть»")
    try:
        await call.message.delete()
        logger.debug(f"[{user_id}] Сообщение удалено успешно")
    except Exception as e:
        logger.warning(f"[{user_id}] Ошибка удаления сообщения: {e}")
    await call.answer("🚫 Меню закрыто")


# --- Пагинация ---
@router.callback_query(F.data.startswith("page_"))
async def handle_pagination(call: CallbackQuery, state: FSMContext):
    # BUG #8 FIX: Валидация callback_data
    user_id = call.from_user.id
    
    if not call.data.startswith("page_"):
        logger.warning(f"[{user_id}] Некорректный callback_data: {call.data}")
        await call.answer("❌ Некорректный запрос", show_alert=True)
        return
    
    try:
        action = call.data.split("_")[1]  # next или prev
        
        # Валидация действия
        if action not in ["next", "prev"]:
            logger.warning(f"[{user_id}] Неизвестное действие пагинации: {action}")
            await call.answer("❌ Неизвестное действие", show_alert=True)
            return
    except (IndexError, ValueError) as e:
        logger.error(f"[{user_id}] Ошибка парсинга callback_data: {e}")
        await call.answer("❌ Ошибка обработки", show_alert=True)
        return
    data = await state.get_data()
    current_page = data.get("page", 0)
    view = data.get("view", "alarms")
    total_pages = data.get("total_pages", 0)

    if action == "next" and current_page < total_pages - 1:
        new_page = current_page + 1
    elif action == "prev" and current_page > 0:
        new_page = current_page - 1
    else:
        new_page = current_page

    await state.update_data(page=new_page)
    logger.info(f"[{user_id}] Перешли на страницу {new_page} для {view}")

    if view == "alarms":
        alarms = bot_state.get_user_active_alarms(user_id)
        text, _ = format_alarms_page(alarms, new_page)
    elif view == "maintenances":
        maintenances = bot_state.get_user_active_maintenances(user_id)
        text, _ = format_maintenances_page(maintenances, new_page)
    else:
        text = "❌ Неизвестное состояние"

    markup = create_refresh_keyboard(current_page=new_page, total_pages=total_pages)
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await call.answer()