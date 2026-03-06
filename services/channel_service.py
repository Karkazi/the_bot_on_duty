"""
Сервис для работы с каналами Telegram.
Централизует логику отправки сообщений, создания тем форума и работы с иконками.
Смена иконок тем — через Bot API (editForumTopic, icon_custom_emoji_id).
"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from aiogram import Bot
from aiogram.types import ForumTopic, FSInputFile

from utils.channel_helpers import safe_send_to_channel, send_to_alarm_channels, validate_channel_access
from config import CONFIG, ktalk_emergency_url

logger = logging.getLogger(__name__)

def _topic_icon_ids_from_config() -> Dict[str, int]:
    """icon_custom_emoji_id для Bot API editForumTopic, читаются из .env."""
    tg_cfg = CONFIG.get("TELEGRAM", {}) or {}
    out: Dict[str, int] = {}
    done_id = (tg_cfg.get("TOPIC_ICON_DONE_ID") or "").strip()
    fire_id = (tg_cfg.get("TOPIC_ICON_FIRE_ID") or "").strip()
    if done_id.isdigit():
        out["✅"] = int(done_id)
    if fire_id.isdigit():
        out["🔥"] = int(fire_id)
    return out


class ChannelService:
    """Сервис для работы с каналами Telegram"""
    
    def __init__(self):
        """Инициализация сервиса"""
        pass
    
    async def send_alarm_notification(
        self,
        bot: Bot,
        alarm_data: Dict[str, Any]
    ) -> bool:
        """
        Отправляет уведомление об аварии в основной канал.
        
        Args:
            bot: Экземпляр бота
            alarm_data: Данные аварии (issue, service, fix_time и т.д.)
        
        Returns:
            True если отправка успешна, False если нет
        """
        if not CONFIG["TELEGRAM"].get("ALARM_CHANNEL_ID"):
            logger.error("ALARM_CHANNEL_ID не настроен в конфигурации")
            return False

        # Формируем сообщение
        from domain.constants import DATETIME_FORMAT
        from datetime import datetime

        issue = alarm_data.get("issue", "не указано")
        service = alarm_data.get("service", "не указан")
        fix_time_str = alarm_data.get("fix_time", "")

        try:
            if isinstance(fix_time_str, str):
                fix_time = datetime.fromisoformat(fix_time_str)
            else:
                fix_time = fix_time_str
        except Exception as e:
            logger.warning("Не удалось разобрать fix_time '%s', используем текущее время: %s", fix_time_str, e)
            fix_time = datetime.now()

        message = (
            f"🚨 Технический сбой\n"
            f"• Проблема: {issue}\n"
            f"• Сервис: {service}\n"
            f"• Исправим до: {fix_time.strftime(DATETIME_FORMAT)}\n"
            f"• Мы уже работаем над устранением сбоя. Спасибо за ваше терпение и понимание!"
        )

        return await send_to_alarm_channels(bot, message, parse_mode=None)
    
    async def create_forum_topic(
        self,
        bot: Bot,
        channel_id: str,
        name: str,
        initial_message: Optional[str] = None
    ) -> Optional[int]:
        """
        Создает тему форума в канале и возвращает topic_id.
        
        Args:
            bot: Экземпляр бота
            channel_id: ID канала
            name: Название темы
            initial_message: Первое сообщение в теме (опционально)
        
        Returns:
            ID темы (message_thread_id) или None при ошибке
        """
        if not channel_id:
            logger.error("channel_id не указан")
            return None
        
        try:
            # Создаем тему
            topic: ForumTopic = await bot.create_forum_topic(
                chat_id=channel_id,
                name=name
            )
            topic_id = topic.message_thread_id
            logger.info(f"Тема форума создана: {name} (topic_id: {topic_id})")
            
            # Отправляем начальное сообщение, если указано
            if initial_message:
                await bot.send_message(
                    chat_id=channel_id,
                    message_thread_id=topic_id,
                    text=initial_message,
                    parse_mode='HTML'
                )
            
            return topic_id
        except Exception as e:
            logger.error(f"Ошибка при создании темы форума: {e}", exc_info=True)
            return None
    
    async def update_topic_icon(
        self,
        bot: Bot,
        channel_id: str,
        topic_id: int,
        icon_emoji: str
    ) -> bool:
        """
        Обновляет иконку темы через Bot API (editForumTopic).
        
        Args:
            bot: Экземпляр aiogram Bot
            channel_id: ID канала (SCM_CHANNEL_ID)
            topic_id: ID темы (message_thread_id)
            icon_emoji: Эмодзи для иконки ("🔥", "✅")
        
        Returns:
            True если обновление успешно, False если нет
        """
        emoji_id = _topic_icon_ids_from_config().get(icon_emoji)
        if emoji_id is None:
            logger.warning(
                f"Нет icon_custom_emoji_id для эмодзи {icon_emoji}. "
                f"Задайте TELEGRAM_TOPIC_ICON_DONE_ID / TELEGRAM_TOPIC_ICON_FIRE_ID в .env"
            )
            return False
        try:
            await bot.edit_forum_topic(
                chat_id=channel_id,
                message_thread_id=topic_id,
                icon_custom_emoji_id=str(emoji_id)
            )
            logger.info(f"Иконка темы {topic_id} обновлена на {icon_emoji}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при обновлении иконки темы {topic_id}: {e}", exc_info=True)
            return False
    
    async def send_to_scm_topic(
        self,
        bot: Bot,
        channel_id: str,
        topic_id: int,
        message: str,
        photo_url: Optional[str] = None,
        document_paths: Optional[List[str]] = None,
    ) -> bool:
        """
        Отправляет сообщение (и при необходимости фото и/или файлы) в тему SCM канала.
        Если задан photo_url — отправляется фото с подписью message; иначе — только текст.
        Если заданы document_paths — после текста/фото отправляются файлы как документы.

        Args:
            bot: Экземпляр бота
            channel_id: ID канала
            topic_id: ID темы
            message: Текст сообщения (или подпись к фото)
            photo_url: URL изображения для пересылки (опционально)
            document_paths: Список путей к файлам для отправки как документов (опционально)

        Returns:
            True если отправка успешна, False если нет
        """
        if not channel_id or not topic_id:
            logger.error("channel_id или topic_id не указаны")
            return False

        caption = (message or "").strip()
        if len(caption) > 1024:
            caption = caption[:1021] + "..."

        try:
            if photo_url and photo_url.strip().startswith("http"):
                await bot.send_photo(
                    chat_id=channel_id,
                    message_thread_id=topic_id,
                    photo=photo_url.strip(),
                    caption=caption or None,
                    parse_mode="HTML",
                )
                logger.info("Фото и сообщение отправлены в тему %s", topic_id)
            else:
                await bot.send_message(
                    chat_id=channel_id,
                    message_thread_id=topic_id,
                    text=message,
                    parse_mode="HTML",
                )
                logger.info("Сообщение отправлено в тему %s", topic_id)
            if document_paths:
                for path in document_paths:
                    if path and Path(path).is_file():
                        await bot.send_document(
                            chat_id=channel_id,
                            message_thread_id=topic_id,
                            document=FSInputFile(path),
                        )
                logger.info("Документы отправлены в тему %s: %s шт.", topic_id, len(document_paths))
            return True
        except Exception as e:
            logger.error("Ошибка при отправке в тему %s: %s", topic_id, e, exc_info=True)
            return False
    
    async def format_alarm_scm_message(
        self,
        alarm_id: str,
        alarm_data: Dict[str, Any],
        jira_url: Optional[str] = None
    ) -> str:
        """
        Форматирует сообщение об аварии для SCM канала.
        
        Args:
            alarm_id: ID аварии
            alarm_data: Данные аварии
            jira_url: URL задачи в Jira (опционально)
        
        Returns:
            Отформатированное сообщение
        """
        issue = alarm_data.get("issue", "не указано")
        service = alarm_data.get("service", "не указан")
        description = alarm_data.get("description", issue)
        
        ktalk_url = ktalk_emergency_url()
        ktalk_line = f"• <i>Ссылка в Ктолк: {ktalk_url}</i>\n" if ktalk_url else ""

        if jira_url:
            message = (
                f"🚨 <b>Технический сбой</b>\n"
                f"• <b>Задача в Jira:</b> <a href='{jira_url}'>{alarm_id}</a>\n"
                f"• <b>Сервис:</b> {service}\n"
                f"• <b>Описание:</b> {description}\n"
                f"{ktalk_line}"
            )
        else:
            message = (
                f"🚨 <b>Технический сбой</b>\n"
                f"• <b>ID:</b> <code>{alarm_id}</code>\n"
                f"• <b>Сервис:</b> {service}\n"
                f"• <b>Описание:</b> {description}\n"
                f"{ktalk_line}"
            )
        
        return message
    
    async def format_alarm_close_message(
        self,
        alarm_id: str,
        issue: str
    ) -> str:
        """
        Форматирует сообщение об устранении аварии для SCM канала.
        
        Args:
            alarm_id: ID аварии
            issue: Описание проблемы
        
        Returns:
            Отформатированное сообщение
        """
        return (
            f"✅ <b>Сбой устранён</b>\n"
            f"• <b>ID:</b> <code>{alarm_id}</code>\n"
            f"• <b>Проблема:</b> {issue}"
        )
    
    async def validate_channel(self, bot: Bot, channel_id: str) -> bool:
        """
        Проверяет доступность канала для бота.
        
        Args:
            bot: Экземпляр бота
            channel_id: ID канала
        
        Returns:
            True если канал доступен, False если нет
        """
        return await validate_channel_access(bot, channel_id)
