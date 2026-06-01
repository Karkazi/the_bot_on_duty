"""
Отправка уведомлений в канал MAX (ALARM).
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def send_to_alarm_channel(
    text: str,
    *,
    strip_html: bool = True,
) -> bool:
    """Отправляет текст в MAX_ALARM_CHANNEL_ID."""
    from config import CONFIG
    from services.max_service import MaxService

    max_cfg = CONFIG.get("MAX") or {}
    channel_id = max_cfg.get("ALARM_CHANNEL_ID")
    if not channel_id:
        logger.error("MAX_ALARM_CHANNEL_ID не установлен в .env")
        return False
    try:
        max_svc = MaxService()
        if not max_svc.is_configured():
            logger.warning("MAX не настроен (MAX_API_URL, MAX_BOT_TOKEN)")
            return False
        ok = await max_svc.send_message(str(channel_id), text, strip_html=strip_html)
        if not ok:
            logger.warning("Не удалось отправить в канал MAX %s", channel_id)
        return bool(ok)
    except Exception as e:
        logger.warning("Ошибка отправки в канал MAX: %s", e, exc_info=True)
        return False


async def send_to_alarm_channels(
    text: str,
    parse_mode: Optional[str] = None,
    photo_file_id: Optional[str] = None,
    photo_url: Optional[str] = None,
    send_telegram: Optional[bool] = None,
    send_max: Optional[bool] = None,
    **kwargs,
) -> bool:
    """
    Обратная совместимость имён: отправка только в MAX.
    Параметры send_telegram / photo_file_id (Telegram) игнорируются.
    """
    if send_max is False:
        return True
    strip = parse_mode != "HTML" if parse_mode else True
    return await send_to_alarm_channel(text, strip_html=strip)
