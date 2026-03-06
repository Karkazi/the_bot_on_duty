"""
Обработчики для обычных сообщений.
Содержит логику ввода и отправки обычных текстовых сообщений в канал.
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from keyboards import create_cancel_keyboard, create_main_keyboard, create_confirmation_keyboard
from keyboards.alarm import create_petlocal_option_keyboard, create_skip_photo_keyboard
from utils.validation import validate_message_text
from utils.callback_validator import validate_callback_in
from utils.telegram_retry import safe_edit_message
from domain.states import NewMessageStates

logger = logging.getLogger(__name__)
router = Router()


@router.message(NewMessageStates.ENTER_MESSAGE_TEXT)
async def enter_message_text(message: Message, state: FSMContext):
    """
    Обработчик ввода текста обычного сообщения.
    
    Валидирует текст и показывает предварительный просмотр перед отправкой.
    """
    message_text = message.text.strip()
    user_id = message.from_user.id
    logger.info(f"[{user_id}] Введен текст сообщения: {message_text[:30]}...")
    
    if message_text == "❌ Отмена":
        logger.info(f"[{user_id}] Действие отменено пользователем")
        await state.clear()
        await message.answer("🚫 Действие отменено", reply_markup=create_main_keyboard())
        return
    
    # Валидация текста сообщения
    is_valid, error_msg = validate_message_text(message_text)
    if not is_valid:
        await message.answer(
            f"{error_msg}\n\n"
            "💡 Попробуйте ввести текст заново.",
            reply_markup=create_cancel_keyboard()
        )
        return
    
    # Сохраняем текст сообщения и переходим к опциональному фото
    await state.update_data(message_text=message_text)
    await state.set_state(NewMessageStates.ENTER_MESSAGE_PHOTO)
    await message.answer(
        "📷 <b>Приложить картинку?</b> Отправьте фото или нажмите «Пропустить».",
        parse_mode='HTML',
        reply_markup=create_skip_photo_keyboard()
    )


def _build_regular_preview(message_text: str, has_photo: bool) -> str:
    """Формирует текст предпросмотра для обычного сообщения."""
    preview = (
        "📄 <b>Предварительный просмотр:</b>\n"
        f"💬 <b>Обычное сообщение</b>\n"
        f"• <b>Текст:</b> {message_text}\n"
        f"• <b>Фото:</b> {'да' if has_photo else 'нет'}"
    )
    return preview


@router.message(NewMessageStates.ENTER_MESSAGE_PHOTO, F.photo)
async def enter_message_photo(message: Message, state: FSMContext):
    """Обработчик прикрепления фото к обычному сообщению (самое большое фото)."""
    user_id = message.from_user.id
    photo = message.photo[-1]
    file_id = photo.file_id
    await state.update_data(photo_file_id=file_id)
    data = await state.get_data()
    message_text = data.get("message_text", "")
    preview_text = _build_regular_preview(message_text, has_photo=True)
    await state.update_data(preview_text=preview_text)
    await state.set_state(NewMessageStates.SELECT_PETLOCAL_OPTION)
    logger.info("[%s] К обычному сообщению приложено фото", user_id)
    await message.answer(
        "📢 <b>Публикуем на Петлокале?</b>",
        parse_mode='HTML',
        reply_markup=create_petlocal_option_keyboard()
    )


@router.message(NewMessageStates.ENTER_MESSAGE_PHOTO, F.text)
async def enter_message_photo_cancel_or_remind(message: Message, state: FSMContext):
    """В шаге фото: отмена или напоминание отправить фото."""
    if message.text.strip() == "❌ Отмена":
        await state.clear()
        await message.answer("🚫 Действие отменено", reply_markup=create_main_keyboard())
        return
    await message.answer(
        "📷 Отправьте фото или нажмите «Пропустить».",
        reply_markup=create_skip_photo_keyboard()
    )


@router.callback_query(NewMessageStates.ENTER_MESSAGE_PHOTO, F.data == "regular_skip_photo")
async def skip_photo_regular(callback: CallbackQuery, state: FSMContext):
    """Пропуск прикрепления фото к обычному сообщению."""
    user_id = callback.from_user.id
    await state.update_data(photo_file_id=None)
    data = await state.get_data()
    message_text = data.get("message_text", "")
    preview_text = _build_regular_preview(message_text, has_photo=False)
    await state.update_data(preview_text=preview_text)
    await state.set_state(NewMessageStates.SELECT_PETLOCAL_OPTION)
    logger.info("[%s] Пропущено прикрепление фото к обычному сообщению", user_id)
    await callback.message.edit_text(
        "📢 <b>Публикуем на Петлокале?</b>",
        parse_mode='HTML',
        reply_markup=create_petlocal_option_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.in_(["petlocal_publish", "petlocal_skip"]))
async def handle_petlocal_option_regular(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора публикации на Петлокале для обычных сообщений"""
    user_id = callback.from_user.id
    
    if not await validate_callback_in(callback, ["petlocal_publish", "petlocal_skip"]):
        return
    
    publish_petlocal = callback.data == "petlocal_publish"
    logger.info(f"[{user_id}] Выбран вариант публикации на Петлокале: {publish_petlocal}")
    await state.update_data(publish_petlocal=publish_petlocal)
    
    # Получаем данные для предварительного просмотра
    data = await state.get_data()
    preview_text = data.get("preview_text", "")
    
    # Добавляем информацию о публикации на Петлокале в предпросмотр
    petlocal_option = "✅ Публикуем на Петлокале" if publish_petlocal else "❌ Не публикуем на Петлокале"
    if preview_text:
        preview_text += f"\n• <b>Петлокал:</b> {petlocal_option}"
    else:
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
