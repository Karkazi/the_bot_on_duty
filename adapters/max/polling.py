# adapters/max/polling.py — запуск polling MAX и привязка к Telegram-боту

import asyncio
import logging
from typing import Any

from config import CONFIG
from adapters.max.handlers import _register_handlers, set_telegram_bot

logger = logging.getLogger(__name__)


async def run_max_polling(telegram_bot: Any) -> None:
    """
    Запускает приём сообщений из MAX (polling).
    telegram_bot: экземпляр aiogram Bot для вызова send_to_alarm_channels и SCM из core.
    Работает пока не отменят задачу (cancel).
    """
    max_cfg = CONFIG.get("MAX", {})
    if not max_cfg.get("BOT_TOKEN"):
        logger.warning("MAX_BOT_TOKEN не задан — polling MAX не запущен")
        return
    if not max_cfg.get("MANAGEMENT_ENABLED", True):
        logger.info("MAX management отключён (MAX_MANAGEMENT_ENABLED) — polling не запущен")
        return

    try:
        from maxapi import Bot, Dispatcher
        from maxapi.types.updates.message_created import MessageCreated
    except ImportError as e:
        logger.warning(
            "maxapi не установлен — управление из MAX недоступно: %s. "
            "Установите в том же окружении, откуда запускаете бота: pip install maxapi brotlicffi",
            e,
        )
        return

    # Патч: при message.sender is None get_ids() в maxapi падает с AttributeError
    _original_get_ids = MessageCreated.get_ids
    def _safe_get_ids(self):
        try:
            if self.message and getattr(self.message, "sender", None) is None:
                recipient = getattr(self.message, "recipient", None)
                chat_id = getattr(recipient, "chat_id", None) if recipient else None
                return (chat_id, None)
            return _original_get_ids(self)
        except AttributeError:
            recipient = getattr(self.message, "recipient", None) if getattr(self, "message", None) else None
            chat_id = getattr(recipient, "chat_id", None) if recipient else None
            return (chat_id, None)
    MessageCreated.get_ids = _safe_get_ids

    set_telegram_bot(telegram_bot)
    bot = Bot()
    dp = Dispatcher()
    _register_handlers(dp)

    logger.info("Запуск polling MAX (управление ботом из MAX)")
    # skip_updates=True: не обрабатывать старые события из очереди (например с теста),
    # чтобы при запуске на сервере бот не повторял команды, накопленные на тесте.
    try:
        await dp.start_polling(bot, skip_updates=True)
    except asyncio.CancelledError:
        logger.info("Polling MAX остановлен (задача отменена)")
        raise
    except Exception as e:
        logger.exception("Ошибка polling MAX: %s", e)
