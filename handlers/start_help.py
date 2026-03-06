# handlers/start_help.py

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from keyboards import create_main_keyboard, create_cancel_keyboard
from aiogram.utils.keyboard import InlineKeyboardBuilder


router = Router()


@router.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "👋 Привет! Я бот для управления событиями и уведомлениями.\nВыберите действие:",
        reply_markup=create_main_keyboard(message.from_user.id)
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def help_command(message: Message):
    help_text = """
📌 <b>Доступные команды:</b>

📢 <b>Сообщить</b> — создать новое сообщение:
   • 🚨 <b>Сбой</b> — технический сбой:
     - Описание проблемы, уровень и сервис
     - Опционально: создание задачи в Jira
     - Опционально: создание темы в канале SCM
     - Время исправления устанавливается автоматически (+1 час)
   • 🔧 <b>Работа</b> — плановые технические работы:
     - Описание работ и недоступные сервисы
     - Выбор времени начала и окончания:
       • Спиннеры (быстро)
       • Календарь (точный выбор)
       • Текстовый ввод
   • 📝 <b>Обычное сообщение</b> — информационное сообщение в канал

🛂 <b>Управлять</b> — управление активными событиями:
   • 🛑 <b>Остановить</b> — завершить сбой или работу
   • ⏳ <b>Продлить</b> — продлить время окончания:
     - Для <b>сбоев</b>: на 30 мин, 1 час или указать своё время текстом
     - Для <b>работ</b>: через спиннеры, календарь или текстовый ввод

📕 <b>Текущие события</b> — посмотреть список активных сбоев и работ

ℹ️ <b>Помощь</b> — показать это окно

⏰ <b>Напоминания:</b>
   Бот автоматически отправляет напоминание за <b>5 минут</b> до окончания сбоя или работы.
   
   Для <b>сбоев</b>:
   • ✅ Да, продлеваем — продлить сбой
   • ❌ Нет, останавливаем — завершить сбой
   
   Для <b>работ</b>:
   • ⏳ Продлить — продлить время окончания
   • ✅ Завершить — завершить работу

🔄 <b>Автоматическое закрытие:</b>
   Сбои с задачей в Jira автоматически закрываются при изменении статуса задачи на "Сбой устранён".
"""
    await message.answer(help_text, reply_markup=create_main_keyboard(message.from_user.id), parse_mode='HTML')


# --- Инлайновый обработчик глобальной отмены ---
@router.callback_query(F.data == "cancel_action")
async def handle_global_cancel(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
    await callback.message.edit_text("🚫 Действие отменено", reply_markup=None)
    await callback.message.answer("Выберите действие:", reply_markup=create_main_keyboard())
    await callback.answer()