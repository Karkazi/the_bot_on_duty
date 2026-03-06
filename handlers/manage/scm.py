"""
Обработчики для работы с SCM каналом.
Содержит логику закрытия сбоев в SCM канале и изменения иконок тем.
"""
import logging
from aiogram import Bot
from typing import Dict

from config import CONFIG
from services.channel_service import ChannelService

logger = logging.getLogger(__name__)
channel_service = ChannelService()


async def handle_scm_alarm_close(bot: Bot, alarm_id: str, alarm: Dict):
    """
    Обработка закрытия сбоя в SCM канале:
    - Отправка сообщения об устранении сбоя
    - Изменение иконки темы на ✅ через Bot API
    - Fallback: изменение названия темы, если иконку не удалось изменить
    
    Args:
        bot: Экземпляр бота
        alarm_id: ID сбоя
        alarm: Данные сбоя
    """
    scm_topic_id = alarm.get("scm_topic_id")
    scm_channel_id = CONFIG["TELEGRAM"].get("SCM_CHANNEL_ID")
    
    logger.info(f"[SCM] Проверка закрытия сбоя {alarm_id} в SCM: scm_topic_id={scm_topic_id}, scm_channel_id={scm_channel_id}")
    
    if not scm_channel_id:
        logger.warning(f"[SCM] SCM_CHANNEL_ID не настроен, пропускаем обработку SCM для сбоя {alarm_id}")
        return
    
    # Если scm_topic_id отсутствует, это означает, что сбой был создан до обновления кода
    if not scm_topic_id:
        issue = alarm.get("issue", "не указано")
        expected_topic_name_old = f"🔥{alarm_id} {issue[:20]}..."
        expected_topic_name_new = f"{alarm_id} {issue[:20]}..."
        logger.warning(
            f"[SCM] У сбоя {alarm_id} нет scm_topic_id (сбой создан до обновления кода). "
            f"Ожидаемое название темы (старый формат): '{expected_topic_name_old}' или (новый формат): '{expected_topic_name_new}'. "
            f"Пытаемся найти тему через поиск сообщений..."
        )
        logger.warning(
            f"[SCM] Не удалось найти тему для сбоя {alarm_id} автоматически. "
            f"Для сбоев, созданных до обновления кода, scm_topic_id отсутствует. "
            f"Для новых сбоев scm_topic_id будет сохраняться автоматически. "
            f"Для обновления темы старого сбоя можно вручную указать message_thread_id в данных сбоя."
        )
        return
    
    try:
        # Формируем и отправляем сообщение об устранении
        issue = alarm.get("issue", "не указано")
        scm_message = await channel_service.format_alarm_close_message(alarm_id, issue)
        
        # Отправляем сообщение в тему
        await channel_service.send_to_scm_topic(
            bot,
            scm_channel_id,
            scm_topic_id,
            scm_message
        )
        logger.info(f"[SCM] Сообщение об устранении отправлено в тему {scm_topic_id} для сбоя {alarm_id}")
        
        # Пытаемся изменить иконку темы (сначала Bot API, при ошибке — MTProto)
        icon_changed = await channel_service.update_topic_icon(
            bot,
            scm_channel_id,
            scm_topic_id,
            "✅"
        )
        
        if icon_changed:
            logger.info(f"[SCM] Иконка темы {scm_topic_id} успешно изменена на ✅ для сбоя {alarm_id}")
        else:
            # Fallback: изменяем название темы (старый подход, если MTProto не работает)
            logger.warning(f"[SCM] Не удалось изменить иконку темы, используем fallback — изменение названия")
            
            issue_short = issue[:20] if len(issue) > 20 else issue
            checkmark_emoji = "\u2705"  # Unicode escape для ✅
            new_topic_name = f"{checkmark_emoji}{alarm_id} {issue_short}..."
            
            # Если название слишком длинное, обрезаем его (максимум 128 символов для названия темы)
            if len(new_topic_name) > 128:
                available_length = 128 - len(checkmark_emoji) - len(alarm_id) - len(" ") - len("...")
                if available_length > 0:
                    issue_short = issue[:available_length] if len(issue) > available_length else issue
                    new_topic_name = f"{checkmark_emoji}{alarm_id} {issue_short}..."
                else:
                    new_topic_name = f"{checkmark_emoji}{alarm_id}"
            
            logger.info(f"[SCM] Формируем новое название темы: '{new_topic_name}' (символов: {len(new_topic_name)})")
            
            # Пытаемся изменить название темы
            try:
                await bot.edit_forum_topic(
                    chat_id=scm_channel_id,
                    message_thread_id=scm_topic_id,
                    name=new_topic_name
                )
                logger.info(f"[SCM] Название темы {scm_topic_id} успешно изменено на '{new_topic_name}' для сбоя {alarm_id}")
            except Exception as edit_error:
                logger.error(f"[SCM] Ошибка при изменении темы {scm_topic_id}: {edit_error}", exc_info=True)
        
    except Exception as e:
        logger.error(f"[SCM] Ошибка при обработке закрытия сбоя {alarm_id} в SCM: {e}", exc_info=True)
