"""
Утилиты для безопасной работы с каналами Telegram и отправки в канал MAX.
"""
import logging
from typing import Optional
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramAPIError

logger = logging.getLogger(__name__)


async def send_to_alarm_channels(
    bot: Bot,
    text: str,
    parse_mode: Optional[str] = "HTML",
    photo_file_id: Optional[str] = None,
    photo_url: Optional[str] = None,
    **kwargs,
) -> bool:
    """
    Отправляет сообщение в канал уведомлений: Telegram (ALARM_CHANNEL_ID) и при наличии настроек — в канал MAX.

    Сначала отправка в Telegram; при успехе при настроенных MAX_API_URL, MAX_BOT_TOKEN и MAX_ALARM_CHANNEL_ID
    дублирует сообщение в MAX. Ошибка отправки в MAX не влияет на возвращаемое значение.

    Args:
        bot: Экземпляр бота (для Telegram).
        text: Текст сообщения (в Telegram при фото используется как caption).
        parse_mode: Режим парсинга для Telegram (по умолчанию HTML).
        photo_file_id: Опционально — file_id фото в Telegram; при заданном отправляется send_photo с caption=text.
        photo_url: Опционально — URL фото; используется если photo_file_id не задан.
        **kwargs: Дополнительные аргументы для send_message/send_photo в Telegram.

    Returns:
        True если сообщение успешно отправлено в Telegram, False иначе.
    """
    from config import CONFIG
    channel_id = CONFIG["TELEGRAM"].get("ALARM_CHANNEL_ID")
    if not channel_id:
        logger.error("ALARM_CHANNEL_ID не установлен в конфигурации")
        return False

    photo_ref = photo_file_id or (photo_url.strip() if photo_url else None)
    if photo_ref:
        ok = await safe_send_photo_to_channel(
            bot, channel_id, photo_ref, caption=text, parse_mode=parse_mode, **kwargs
        )
    else:
        ok = await safe_send_to_channel(bot, channel_id, text, parse_mode=parse_mode, **kwargs)
    if not ok:
        return False

    # Дублирование в канал MAX при наличии настроек
    max_cfg = CONFIG.get("MAX", {})
    max_channel_id = max_cfg.get("ALARM_CHANNEL_ID")
    if max_channel_id:
        try:
            from services.max_service import MaxService
            max_svc = MaxService()
            if not max_svc.is_configured():
                logger.warning(
                    "MAX: задан MAX_ALARM_CHANNEL_ID, но MAX не настроен полностью. "
                    "Укажите MAX_API_URL и MAX_BOT_TOKEN в .env"
                )
            else:
                logger.info("Отправка дубликата сообщения в канал MAX (channel_id=%s)", max_channel_id)
                ok_max = await max_svc.send_message(max_channel_id, text, strip_html=True)
                if not ok_max:
                    logger.warning("Отправка в канал MAX завершилась с ошибкой (см. логи выше)")
        except Exception as e:
            logger.warning("Не удалось отправить сообщение в канал MAX: %s", e, exc_info=True)
    else:
        # Все три параметра MAX должны быть заданы для дублирования
        if max_cfg.get("API_URL") or max_cfg.get("BOT_TOKEN"):
            logger.debug(
                "MAX: API_URL или BOT_TOKEN заданы, но MAX_ALARM_CHANNEL_ID не указан — дублирование в MAX пропущено"
            )
    return True


async def safe_send_photo_to_channel(
    bot: Bot,
    channel_id: str,
    photo_ref: str,
    caption: str = "",
    parse_mode: Optional[str] = "HTML",
    **kwargs,
) -> bool:
    """
    Безопасная отправка фото в канал с подписью (caption).
    photo_ref может быть file_id Telegram или прямой URL.

    Returns:
        True если отправлено успешно, False иначе.
    """
    if not channel_id:
        logger.error("ALARM_CHANNEL_ID не установлен в конфигурации")
        return False
    try:
        await bot.send_photo(
            chat_id=channel_id,
            photo=photo_ref,
            caption=caption,
            parse_mode=parse_mode,
            **kwargs
        )
        logger.debug("✅ Фото успешно отправлено в канал %s", channel_id)
        return True
    except TelegramBadRequest as e:
        logger.error("❌ Ошибка Telegram API при отправке фото в канал %s: %s", channel_id, e)
        return False
    except TelegramForbiddenError as e:
        logger.error("❌ Бот заблокирован или не имеет прав в канале %s: %s", channel_id, e)
        return False
    except Exception as e:
        logger.error("❌ Неожиданная ошибка при отправке фото в канал %s: %s", channel_id, e, exc_info=True)
        return False


async def safe_send_to_channel(
    bot: Bot,
    channel_id: str,
    text: str,
    parse_mode: Optional[str] = 'HTML',
    **kwargs
) -> bool:
    """
    Безопасная отправка сообщения в канал с обработкой ошибок.
    
    Args:
        bot: Экземпляр бота
        channel_id: ID канала (должен начинаться с -100 для супергрупп)
        text: Текст сообщения
        parse_mode: Режим парсинга (по умолчанию HTML)
        **kwargs: Дополнительные параметры для send_message
    
    Returns:
        True если сообщение отправлено успешно, False в противном случае
    """
    if not channel_id:
        logger.error("❌ ALARM_CHANNEL_ID не установлен в конфигурации")
        return False
    
    # Валидация формата ID канала
    if not channel_id.startswith('-100'):
        logger.warning(f"⚠️ Возможно неверный формат ID канала: {channel_id}. Ожидается формат -100...")
    
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode=parse_mode,
            **kwargs
        )
        logger.debug(f"✅ Сообщение успешно отправлено в канал {channel_id}")
        return True
        
    except TelegramBadRequest as e:
        error_message = str(e)
        if "chat not found" in error_message.lower():
            logger.error(
                f"❌ Канал не найден (ID: {channel_id}). "
                f"Проверьте:\n"
                f"  1. Бот добавлен в канал как администратор\n"
                f"  2. ID канала указан правильно (формат: -100...)\n"
                f"  3. Канал существует и доступен"
            )
        elif "chat_id is empty" in error_message.lower():
            logger.error(f"❌ ID канала пустой: {channel_id}")
        else:
            logger.error(f"❌ Ошибка Telegram API при отправке в канал {channel_id}: {error_message}")
        return False
        
    except TelegramForbiddenError as e:
        logger.error(
            f"❌ Бот заблокирован в канале или не имеет прав (ID: {channel_id}). "
            f"Убедитесь, что бот добавлен в канал как администратор"
        )
        return False
        
    except TelegramAPIError as e:
        logger.error(f"❌ Ошибка Telegram API при отправке в канал {channel_id}: {e}")
        return False
        
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при отправке в канал {channel_id}: {e}", exc_info=True)
        return False


async def validate_channel_access(bot: Bot, channel_id: str) -> bool:
    """
    Проверяет доступность канала для бота.
    
    Args:
        bot: Экземпляр бота
        channel_id: ID канала
    
    Returns:
        True если канал доступен, False в противном случае
    """
    if not channel_id:
        return False
    
    try:
        chat = await bot.get_chat(channel_id)
        logger.debug(f"✅ Канал доступен: {chat.title} (ID: {channel_id})")
        return True
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower():
            logger.warning(f"⚠️ Канал не найден: {channel_id}")
        else:
            logger.warning(f"⚠️ Ошибка при проверке канала {channel_id}: {e}")
        return False
    except Exception as e:
        logger.warning("⚠️ Ошибка при проверке канала %s: %s", channel_id, e, exc_info=True)
        return False

