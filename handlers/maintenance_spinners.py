"""
Обработчики спиннеров для выбора времени регламентных работ
"""

import logging
from datetime import datetime as dt, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from domain.constants import MAINTENANCE_TIME_SPINNER_CONFIG, MAINTENANCE_TIME_STEPS_ORDER
from domain.states import NewMessageStates, StopStates
from keyboards import (
    create_time_spinner_keyboard, 
    create_spinner_progress_bar, 
    create_cancel_keyboard,
    create_extend_time_spinner_keyboard,
    create_main_keyboard
)
from utils.maintenance_time_utils import MaintenanceTimeSpinner
from bot_state import bot_state
from config import CONFIG
from utils.channel_helpers import send_to_alarm_channels
from domain.constants import DATETIME_FORMAT

logger = logging.getLogger(__name__)

# Создаем отдельный router для спиннеров
router = Router()


async def safe_answer_callback(call: CallbackQuery, text: str = None, show_alert: bool = False):
    """
    Безопасный ответ на callback-запрос с обработкой устаревших запросов
    
    Args:
        call: CallbackQuery объект
        text: Текст ответа (опционально)
        show_alert: Показывать ли alert (по умолчанию False)
    """
    try:
        await call.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest as e:
        error_msg = str(e)
        if "query is too old" in error_msg or "query ID is invalid" in error_msg:
            # Игнорируем устаревшие callback-запросы
            logger.debug(f"[{call.from_user.id}] Игнорируем устаревший callback-запрос")
            return
        # Пробрасываем другие ошибки
        raise


class MaintenanceSpinnerStates(StatesGroup):
    """FSM состояния для спиннеров времени"""
    SELECTING_TIME_SPINNER = State()
    CONFIRMING_TIME = State()


@router.callback_query(F.data == "maint_method_spinners")
async def start_spinners(call: CallbackQuery, state: FSMContext):
    """
    Начать процесс выбора времени через спиннеры
    
    Инициализируем значения по умолчанию:
    - Дата: сегодня (0)
    - Время начала: 10:00
    - Время окончания: 12:00
    """
    user_id = call.from_user.id
    
    try:
        # Инициализируем значения
        spinner_data = {
            "date": 0,  # Дата начала (сегодня)
            "hour_start": 10,
            "minute_start": 0,
            "date_end": 0,  # Дата окончания (по умолчанию та же, что и начало)
            "hour_end": 12,
            "minute_end": 0,
            "current_step_index": 0,  # Индекс текущего шага (0-5)
        }
        
        await state.update_data(maintenance_spinner=spinner_data)
        await state.set_state(MaintenanceSpinnerStates.SELECTING_TIME_SPINNER)
        
        logger.info(f"[{user_id}] Начинают выбор времени через спиннеры")
        
        # Показываем первый спиннер
        await show_current_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при инициализации спиннеров: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка инициализации", show_alert=True)


async def show_current_spinner(
    message,
    state: FSMContext,
    user_id: int
):
    """
    Показать текущий спиннер на основе шага
    """
    try:
        data = await state.get_data()
        spinner_data = data.get("maintenance_spinner", {})
        step_index = spinner_data.get("current_step_index", 0)
        
        # Получаем текущий тип поля
        if step_index >= len(MAINTENANCE_TIME_STEPS_ORDER):
            # Завершить выбор
            await finalize_spinner_selection(message, state, user_id)
            return
        
        field_type = MAINTENANCE_TIME_STEPS_ORDER[step_index]
        config = MAINTENANCE_TIME_SPINNER_CONFIG[field_type]
        
        current_value = spinner_data.get(field_type, config["min"])
        
        # Формируем сообщение
        progress = create_spinner_progress_bar(step_index + 1, len(MAINTENANCE_TIME_STEPS_ORDER))
        
        # Форматируем значение для отображения
        if field_type in ["date", "date_end"]:
            from datetime import datetime
            value_display = config["format"](current_value, datetime.now())
        else:
            value_display = config["format"](current_value)
        
        message_text = (
            f"{progress}\n\n"
            f"{config['label']}\n\n"
            f"Текущее значение: {value_display}\n\n"
            f"💡 Нажимайте ⬆️ и ⬇️ для изменения"
        )
        
        # Создаем спиннер
        keyboard = create_time_spinner_keyboard(
            field_type=field_type,
            current_value=current_value,
            label=config["label"],
            min_val=config["min"],
            max_val=config["max"],
            step=config.get("step", 1)
        )
        
        await message.edit_text(message_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при отображении спиннера: {e}", exc_info=True)
        await message.edit_text("❌ Ошибка отображения спиннера")


@router.callback_query(F.data.startswith("spinner_inc_"))
async def spinner_increment(call: CallbackQuery, state: FSMContext):
    """
    Увеличить значение спиннера (⬆️)
    
    callback_data: spinner_inc_{field_type}_{current_value}_{step}
    Парсим с конца, так как field_type может содержать подчеркивания (hour_start, minute_start и т.д.)
    """
    user_id = call.from_user.id
    
    try:
        # Парсим callback_data с конца
        # Формат: spinner_inc_{field_type}_{current_value}_{step}
        # Например: spinner_inc_hour_start_10_1
        parts = call.data.split("_")
        if len(parts) < 5:
            raise ValueError("Неверный формат callback_data")
        
        # Последний элемент - step, предпоследний - current_value
        step = int(parts[-1])
        current_value = int(parts[-2])
        # Все между "spinner_inc_" и current_value - это field_type
        field_type = "_".join(parts[2:-2])
        
        # Вычисляем новое значение
        new_value = MaintenanceTimeSpinner.increment_value(field_type, current_value)
        
        # Обновляем в состоянии
        data = await state.get_data()
        spinner_data = data.get("maintenance_spinner", {})
        spinner_data[field_type] = new_value
        
        await state.update_data(maintenance_spinner=spinner_data)
        
        logger.debug(f"[{user_id}] Спиннер {field_type}: {current_value} → {new_value}")
        
        # Обновляем сообщение
        await show_current_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при увеличении спиннера: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data.startswith("spinner_dec_"))
async def spinner_decrement(call: CallbackQuery, state: FSMContext):
    """
    Уменьшить значение спиннера (⬇️)
    
    callback_data: spinner_dec_{field_type}_{current_value}_{step}
    Парсим с конца, так как field_type может содержать подчеркивания (hour_start, minute_start и т.д.)
    """
    user_id = call.from_user.id
    
    try:
        # Парсим callback_data с конца
        # Формат: spinner_dec_{field_type}_{current_value}_{step}
        # Например: spinner_dec_hour_start_10_1
        parts = call.data.split("_")
        if len(parts) < 5:
            raise ValueError("Неверный формат callback_data")
        
        # Последний элемент - step, предпоследний - current_value
        step = int(parts[-1])
        current_value = int(parts[-2])
        # Все между "spinner_dec_" и current_value - это field_type
        field_type = "_".join(parts[2:-2])
        
        # Вычисляем новое значение
        new_value = MaintenanceTimeSpinner.decrement_value(field_type, current_value)
        
        # Обновляем в состоянии
        data = await state.get_data()
        spinner_data = data.get("maintenance_spinner", {})
        spinner_data[field_type] = new_value
        
        await state.update_data(maintenance_spinner=spinner_data)
        
        logger.debug(f"[{user_id}] Спиннер {field_type}: {current_value} → {new_value}")
        
        # Обновляем сообщение
        await show_current_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при уменьшении спиннера: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data == "spinner_next_step")
async def spinner_next_step(call: CallbackQuery, state: FSMContext):
    """
    Перейти к следующему спиннеру (кнопка ✅ Дальше)
    """
    user_id = call.from_user.id
    
    try:
        data = await state.get_data()
        spinner_data = data.get("maintenance_spinner", {})
        current_step_index = spinner_data.get("current_step_index", 0)
        
        # Валидация не нужна на промежуточных шагах, так как время окончания еще не выбрано
        # Валидация будет выполнена в finalize_spinner_selection после выбора всех значений
        
        # Переходим к следующему шагу
        spinner_data["current_step_index"] = current_step_index + 1
        await state.update_data(maintenance_spinner=spinner_data)
        
        logger.info(f"[{user_id}] Переход на шаг {current_step_index + 1}")
        
        # Показываем следующий спиннер или завершаем
        await show_current_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при переходе к следующему шагу: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data == "spinner_prev_step")
async def spinner_prev_step(call: CallbackQuery, state: FSMContext):
    """
    Вернуться к предыдущему спиннеру (кнопка ⏪ Назад)
    """
    user_id = call.from_user.id
    
    try:
        data = await state.get_data()
        spinner_data = data.get("maintenance_spinner", {})
        current_step_index = spinner_data.get("current_step_index", 0)
        
        # Если это первый шаг, выходим
        if current_step_index == 0:
            await state.clear()
            await call.message.edit_text("🚫 Выбор отменён")
            await safe_answer_callback(call)
            return
        
        # Возвращаемся на предыдущий шаг
        spinner_data["current_step_index"] = current_step_index - 1
        await state.update_data(maintenance_spinner=spinner_data)
        
        logger.info(f"[{user_id}] Возврат на шаг {current_step_index - 1}")
        
        # Показываем предыдущий спиннер
        await show_current_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при возврате: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data == "spinner_cancel")
async def spinner_cancel(call: CallbackQuery, state: FSMContext):
    """
    Отменить выбор времени (кнопка ❌ Отмена)
    """
    user_id = call.from_user.id
    
    logger.info(f"[{user_id}] Отмена выбора времени через спиннеры")
    
    await state.clear()
    await call.message.edit_text(
        "🚫 Выбор времени отменён",
        reply_markup=None
    )
    await safe_answer_callback(call)


async def finalize_spinner_selection(
    message,
    state: FSMContext,
    user_id: int
):
    """
    Завершить выбор времени через спиннеры
    Сохранить в основное состояние для регламентных работ
    """
    try:
        data = await state.get_data()
        spinner_data = data.get("maintenance_spinner", {})
        
        # Извлекаем значения
        date_offset = spinner_data.get("date", 0)
        hour_start = spinner_data.get("hour_start", 10)
        minute_start = spinner_data.get("minute_start", 0)
        date_end_offset = spinner_data.get("date_end", 0)
        hour_end = spinner_data.get("hour_end", 12)
        minute_end = spinner_data.get("minute_end", 0)
        
        # Строим datetime объекты
        start_time = MaintenanceTimeSpinner.build_datetime(date_offset, hour_start, minute_start)
        end_time = MaintenanceTimeSpinner.build_datetime(date_end_offset, hour_end, minute_end)
        
        # Валидация финального времени
        now = dt.now()
        if start_time < now:
            await message.edit_text(
                "⚠️ Время начала уже прошло.\n"
                "Пожалуйста, выберите другое время."
            )
            # Возвращаемся на первый шаг
            spinner_data["current_step_index"] = 0
            await state.update_data(maintenance_spinner=spinner_data)
            await show_current_spinner(message, state, user_id)
            return
        
        if end_time <= start_time:
            await message.edit_text(
                "⚠️ Время окончания должно быть позже начала.\n"
                "Пожалуйста, выберите снова."
            )
            spinner_data["current_step_index"] = 0
            await state.update_data(maintenance_spinner=spinner_data)
            await show_current_spinner(message, state, user_id)
            return
        
        # Сохраняем в основное состояние для регламентных работ
        await state.update_data(
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat()
        )
        
        logger.info(f"[{user_id}] Время выбрано через спиннеры: {start_time} - {end_time}")
        
        # Переходим к следующему шагу
        await state.set_state(NewMessageStates.ENTER_UNAVAILABLE_SERVICES)
        
        # Показываем предварительный просмотр
        time_display = MaintenanceTimeSpinner.format_time_display(
            date_offset, hour_start, minute_start, date_end_offset, hour_end, minute_end
        )
        
        await message.edit_text(
            f"✅ Время регламентных работ:\n\n{time_display}\n\n"
            f"🔌 Что будет недоступно во время работ?",
            reply_markup=create_cancel_keyboard()
        )
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при завершении выбора спиннеров: {e}", exc_info=True)
        await message.edit_text("❌ Ошибка обработки. Начните заново.")


# ========================
# 🎚️ СПИННЕРЫ ДЛЯ ПРОДЛЕНИЯ РАБОТ
# ========================

# Порядок шагов для продления работ (дата, час и минута окончания)
MAINTENANCE_EXTEND_STEPS_ORDER = ["date_end", "hour_end", "minute_end"]


@router.callback_query(F.data == "maint_extend_spinners")
async def start_extend_spinners(call: CallbackQuery, state: FSMContext):
    """
    Начать процесс выбора нового времени окончания через спиннеры при продлении работ
    """
    user_id = call.from_user.id
    logger.info(f"[{user_id}] Получен callback maint_extend_spinners")
    
    try:
        data = await state.get_data()
        # Может быть item_id (из меню управления) или work_id (из напоминания)
        item_id = data.get('item_id') or data.get('work_id')
        
        if not item_id:
            await safe_answer_callback(call, "❌ Ошибка: не найден ID работы", show_alert=True)
            return
        
        maint = bot_state.active_maintenances.get(item_id)
        if not maint:
            await safe_answer_callback(call, "❌ Работа не найдена", show_alert=True)
            return
        
        # Получаем текущее время окончания
        end_time_str = maint.get("end_time")
        if isinstance(end_time_str, str):
            end_time = dt.fromisoformat(end_time_str)
        elif isinstance(end_time_str, dt):
            end_time = end_time_str
        else:
            await safe_answer_callback(call, "❌ Ошибка: некорректное время окончания", show_alert=True)
            return
        
        # Вычисляем смещение даты от сегодня (0 = сегодня, 1 = завтра и т.д.)
        now = dt.now()
        date_offset = (end_time.date() - now.date()).days
        if date_offset < 0:
            date_offset = 0  # Если дата в прошлом, используем сегодня
        
        # Инициализируем значения на основе текущего времени окончания
        spinner_data = {
            "date_end": date_offset,
            "hour_end": end_time.hour,
            "minute_end": end_time.minute,
            "current_step_index": 0,  # Индекс текущего шага (0-2)
            "item_id": item_id,  # Сохраняем ID работы
            "original_end_time": end_time.isoformat()  # Сохраняем оригинальное время для валидации
        }
        
        await state.update_data(maintenance_extend_spinner=spinner_data)
        await state.set_state(MaintenanceSpinnerStates.SELECTING_TIME_SPINNER)
        
        logger.info(f"[{user_id}] Начинают выбор нового времени окончания через спиннеры для работы {item_id}")
        
        # Показываем первый спиннер
        await show_extend_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при инициализации спиннеров продления: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка инициализации", show_alert=True)


async def show_extend_spinner(
    message,
    state: FSMContext,
    user_id: int
):
    """
    Показать текущий спиннер для продления работ
    """
    try:
        data = await state.get_data()
        spinner_data = data.get("maintenance_extend_spinner", {})
        step_index = spinner_data.get("current_step_index", 0)
        
        # Получаем текущий тип поля
        if step_index >= len(MAINTENANCE_EXTEND_STEPS_ORDER):
            # Завершить выбор
            await finalize_extend_spinner_selection(message, state, user_id)
            return
        
        field_type = MAINTENANCE_EXTEND_STEPS_ORDER[step_index]
        config = MAINTENANCE_TIME_SPINNER_CONFIG[field_type]
        
        current_value = spinner_data.get(field_type, config["min"])
        
        # Формируем сообщение
        progress = create_spinner_progress_bar(step_index + 1, len(MAINTENANCE_EXTEND_STEPS_ORDER))
        
        # Форматируем значение для отображения
        if field_type == "date_end":
            from datetime import datetime
            value_display = config["format"](current_value, datetime.now())
        else:
            value_display = config["format"](current_value)
        
        message_text = (
            f"{progress}\n\n"
            f"{config['label']}\n\n"
            f"Текущее значение: {value_display}\n\n"
            f"💡 Нажимайте ⬆️ и ⬇️ для изменения"
        )
        
        # Создаем спиннер
        keyboard = create_extend_time_spinner_keyboard(
            field_type=field_type,
            current_value=current_value,
            label=config["label"],
            min_val=config["min"],
            max_val=config["max"],
            step=config.get("step", 1)
        )
        
        await message.edit_text(message_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при отображении спиннера продления: {e}", exc_info=True)
        await message.edit_text("❌ Ошибка отображения спиннера")


@router.callback_query(F.data.startswith("extend_spinner_inc_"))
async def extend_spinner_increment(call: CallbackQuery, state: FSMContext):
    """Увеличить значение спиннера при продлении работ"""
    user_id = call.from_user.id
    
    try:
        parts = call.data.split("_")
        if len(parts) < 5:
            raise ValueError("Неверный формат callback_data")
        
        step = int(parts[-1])
        current_value = int(parts[-2])
        field_type = "_".join(parts[3:-2])
        
        new_value = MaintenanceTimeSpinner.increment_value(field_type, current_value)
        
        data = await state.get_data()
        spinner_data = data.get("maintenance_extend_spinner", {})
        spinner_data[field_type] = new_value
        
        await state.update_data(maintenance_extend_spinner=spinner_data)
        
        logger.debug(f"[{user_id}] Спиннер продления {field_type}: {current_value} → {new_value}")
        
        await show_extend_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при увеличении спиннера продления: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data.startswith("extend_spinner_dec_"))
async def extend_spinner_decrement(call: CallbackQuery, state: FSMContext):
    """Уменьшить значение спиннера при продлении работ"""
    user_id = call.from_user.id
    
    try:
        parts = call.data.split("_")
        if len(parts) < 5:
            raise ValueError("Неверный формат callback_data")
        
        step = int(parts[-1])
        current_value = int(parts[-2])
        field_type = "_".join(parts[3:-2])
        
        new_value = MaintenanceTimeSpinner.decrement_value(field_type, current_value)
        
        data = await state.get_data()
        spinner_data = data.get("maintenance_extend_spinner", {})
        spinner_data[field_type] = new_value
        
        await state.update_data(maintenance_extend_spinner=spinner_data)
        
        logger.debug(f"[{user_id}] Спиннер продления {field_type}: {current_value} → {new_value}")
        
        await show_extend_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при уменьшении спиннера продления: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data == "extend_spinner_next_step")
async def extend_spinner_next_step(call: CallbackQuery, state: FSMContext):
    """Перейти к следующему спиннеру при продлении работ"""
    user_id = call.from_user.id
    
    try:
        data = await state.get_data()
        spinner_data = data.get("maintenance_extend_spinner", {})
        current_step_index = spinner_data.get("current_step_index", 0)
        
        # Переходим к следующему шагу
        spinner_data["current_step_index"] = current_step_index + 1
        await state.update_data(maintenance_extend_spinner=spinner_data)
        
        logger.info(f"[{user_id}] Переход на шаг {current_step_index + 1} при продлении")
        
        await show_extend_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при переходе к следующему шагу продления: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data == "extend_spinner_prev_step")
async def extend_spinner_prev_step(call: CallbackQuery, state: FSMContext):
    """Вернуться к предыдущему спиннеру при продлении работ"""
    user_id = call.from_user.id
    
    try:
        data = await state.get_data()
        spinner_data = data.get("maintenance_extend_spinner", {})
        current_step_index = spinner_data.get("current_step_index", 0)
        
        if current_step_index == 0:
            await state.clear()
            await call.message.edit_text("🚫 Выбор отменён")
            await safe_answer_callback(call)
            return
        
        spinner_data["current_step_index"] = current_step_index - 1
        await state.update_data(maintenance_extend_spinner=spinner_data)
        
        logger.info(f"[{user_id}] Возврат на шаг {current_step_index - 1} при продлении")
        
        await show_extend_spinner(call.message, state, user_id)
        await safe_answer_callback(call)
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при возврате при продлении: {e}", exc_info=True)
        await safe_answer_callback(call, "❌ Ошибка обработки", show_alert=True)


@router.callback_query(F.data == "extend_spinner_cancel")
async def extend_spinner_cancel(call: CallbackQuery, state: FSMContext):
    """Отменить выбор времени при продлении работ"""
    user_id = call.from_user.id
    
    logger.info(f"[{user_id}] Отмена выбора времени через спиннеры при продлении")
    
    await state.clear()
    await call.message.edit_text(
        "🚫 Выбор времени отменён",
        reply_markup=None
    )
    await safe_answer_callback(call)


async def finalize_extend_spinner_selection(
    message,
    state: FSMContext,
    user_id: int
):
    """
    Завершить выбор нового времени окончания через спиннеры при продлении работ
    """
    try:
        data = await state.get_data()
        spinner_data = data.get("maintenance_extend_spinner", {})
        item_id = spinner_data.get("item_id")
        original_end_time_str = spinner_data.get("original_end_time")
        
        if not item_id:
            await message.edit_text("❌ Ошибка: не найден ID работы")
            return
        
        maint = bot_state.active_maintenances.get(item_id)
        if not maint:
            await message.edit_text("❌ Работа не найдена")
            return
        
        # Извлекаем значения
        date_end_offset = spinner_data.get("date_end", 0)
        hour_end = spinner_data.get("hour_end", 12)
        minute_end = spinner_data.get("minute_end", 0)
        
        # Получаем текущее время окончания для валидации
        if original_end_time_str:
            original_end_time = dt.fromisoformat(original_end_time_str) if isinstance(original_end_time_str, str) else original_end_time_str
        else:
            end_time_str = maint.get("end_time")
            if isinstance(end_time_str, str):
                original_end_time = dt.fromisoformat(end_time_str)
            elif isinstance(end_time_str, dt):
                original_end_time = end_time_str
            else:
                await message.edit_text("❌ Ошибка: некорректное время окончания")
                return
        
        # Строим новое время окончания на основе смещения даты от сегодня
        from utils.maintenance_time_utils import MaintenanceTimeSpinner
        new_end_time = MaintenanceTimeSpinner.build_datetime(date_end_offset, hour_end, minute_end)
        
        # Валидация: новое время должно быть позже текущего времени окончания
        if new_end_time <= original_end_time:
            await message.edit_text(
                "⚠️ Новое время окончания должно быть позже текущего.\n"
                "Пожалуйста, выберите снова."
            )
            spinner_data["current_step_index"] = 0
            await state.update_data(maintenance_extend_spinner=spinner_data)
            await show_extend_spinner(message, state, user_id)
            return
        
        # Обновляем время окончания
        maint["end_time"] = new_end_time.isoformat() if isinstance(new_end_time, dt) else new_end_time
        # Сбрасываем флаг напоминания при продлении
        if "reminder_sent_for" in maint:
            del maint["reminder_sent_for"]
        
        logger.info(f"[{user_id}] Время окончания работы {item_id} изменено через спиннеры: {new_end_time}")
        
        # Отправляем сообщение в канал
        text = (
            f"🔄 <b>Работа продлена</b>\n"
            f"• <b>Описание:</b> {maint['description']}\n"
            f"• <b>Новое время окончания:</b> {new_end_time.strftime(DATETIME_FORMAT)}"
        )
        if not await send_to_alarm_channels(message.bot, text):
            logger.error(f"[{user_id}] Не удалось отправить сообщение о продлении работы")
        else:
            logger.info(f"[{user_id}] Сообщение о продлении работы отправлено в канал")
        
        # Сохраняем состояние
        await bot_state.save_state()
        
        # Уведомляем пользователя
        await message.edit_text(
            f"✅ Работа {item_id} продлена до {new_end_time.strftime(DATETIME_FORMAT)}",
            reply_markup=None
        )
        await message.answer("Выберите действие:", reply_markup=create_main_keyboard())
        
        # Очищаем FSM состояние
        await state.clear()
        
    except Exception as e:
        logger.error(f"[{user_id}] Ошибка при завершении выбора спиннеров продления: {e}", exc_info=True)
        await message.edit_text("❌ Ошибка обработки. Начните заново.")


@router.callback_query(F.data == "maint_extend_text")
async def handle_extend_text_method(call: CallbackQuery, state: FSMContext):
    """Обработчик выбора текстового ввода при продлении работ"""
    user_id = call.from_user.id
    logger.info(f"[{user_id}] Получен callback maint_extend_text")
    logger.info(f"[{user_id}] Выбран способ ввода времени: текстом")
    
    await call.message.edit_text("Введите новое время окончания в формате dd.mm.yyyy hh:mm")
    await state.set_state(StopStates.ENTER_MAINTENANCE_END)
    await safe_answer_callback(call)

