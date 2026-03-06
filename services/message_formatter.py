"""
Сервис для форматирования сообщений.
Содержит логику форматирования сообщений для разных типов событий.
"""
from datetime import datetime
from typing import Dict, Optional

from domain.constants import DATETIME_FORMAT
from config import ktalk_emergency_url


class MessageFormatter:
    """Сервис для форматирования сообщений"""
    
    @staticmethod
    def format_alarm_message(
        issue: str,
        service: str,
        fix_time: datetime,
        jira_url: Optional[str] = None,
        alarm_id: Optional[str] = None
    ) -> str:
        """
        Форматирует сообщение об аварии для основного канала.
        
        Args:
            issue: Описание проблемы
            service: Затронутый сервис
            fix_time: Время исправления
            jira_url: Ссылка на задачу в Jira (если есть)
            alarm_id: ID аварии
        
        Returns:
            Отформатированное сообщение
        """
        fix_time_str = fix_time.strftime(DATETIME_FORMAT) if isinstance(fix_time, datetime) else fix_time
        
        message = (
            f"🚨 Технический сбой\n"
            f"• Проблема: {issue}\n"
            f"• Сервис: {service}\n"
            f"• Исправим до: {fix_time_str}\n"
            f"• Мы уже работаем над устранением сбоя. Спасибо за ваше терпение и понимание!"
        )
        
        return message
    
    @staticmethod
    def format_alarm_message_scm(
        issue: str,
        service: str,
        jira_url: Optional[str] = None,
        alarm_id: Optional[str] = None
    ) -> str:
        """
        Форматирует сообщение об аварии для SCM канала.
        
        Args:
            issue: Описание проблемы
            service: Затронутый сервис
            jira_url: Ссылка на задачу в Jira (если есть)
            alarm_id: ID аварии
        
        Returns:
            Отформатированное сообщение в HTML
        """
        ktalk_url = ktalk_emergency_url()
        ktalk_line = f"• <i>Ссылка в Ктолк: {ktalk_url}</i>\n" if ktalk_url else ""

        if jira_url:
            message = (
                f"🚨 <b>Технический сбой</b>\n"
                f"• <b>Задача в Jira:</b> <a href='{jira_url}'>{alarm_id}</a>\n"
                f"• <b>Сервис:</b> {service}\n"
                f"• <b>Описание:</b> {issue}\n"
                f"{ktalk_line}"
            )
        else:
            message = (
                f"🚨 <b>Технический сбой</b>\n"
                f"• <b>ID:</b> <code>{alarm_id}</code>\n"
                f"• <b>Сервис:</b> {service}\n"
                f"• <b>Описание:</b> {issue}\n"
                f"{ktalk_line}"
            )
        
        return message
    
    @staticmethod
    def format_alarm_extended_message(
        issue: str,
        new_fix_time: datetime
    ) -> str:
        """
        Форматирует сообщение о продлении аварии.
        
        Args:
            issue: Описание проблемы
            new_fix_time: Новое время исправления
        
        Returns:
            Отформатированное сообщение
        """
        new_fix_time_str = new_fix_time.strftime(DATETIME_FORMAT) if isinstance(new_fix_time, datetime) else new_fix_time
        
        message = (
            f"🔄 <b>Сбой продлён</b>\n"
            f"• <b>Проблема:</b> {issue}\n"
            f"• <b>Новое время окончания:</b> {new_fix_time_str}"
        )
        
        return message
    
    @staticmethod
    def format_alarm_closed_message(issue: str) -> str:
        """
        Форматирует сообщение о закрытии аварии.
        
        Args:
            issue: Описание проблемы
        
        Returns:
            Отформатированное сообщение
        """
        return f"✅ Сбой устранён\n• Проблема: {issue}"
    
    @staticmethod
    def format_maintenance_message(
        description: str,
        start_time: datetime,
        end_time: datetime,
        unavailable_services: str
    ) -> str:
        """
        Форматирует сообщение о регламентных работах.
        
        Args:
            description: Описание работ
            start_time: Время начала
            end_time: Время окончания
            unavailable_services: Недоступные сервисы
        
        Returns:
            Отформатированное сообщение
        """
        start_time_str = start_time.strftime(DATETIME_FORMAT) if isinstance(start_time, datetime) else start_time
        end_time_str = end_time.strftime(DATETIME_FORMAT) if isinstance(end_time, datetime) else end_time
        
        message = (
            f"🔧 <b>Проводим плановые технические работы – станет ещё лучше!</b>\n"
            f"• <b>Описание:</b> {description}\n"
            f"• <b>Начало:</b> {start_time_str}\n"
            f"• <b>Конец:</b> {end_time_str}\n"
            f"• <b>Недоступно:</b> {unavailable_services}\n"
            f"• <i>Спасибо за понимание! Эти изменения – важный шаг к тому, чтобы сервис стал ещё удобнее и надёжнее для вас 💙</i>\n"
            f"• <i>Если возникнут вопросы – наша поддержка всегда на связи</i>\n"
            f"• <i>С заботой, Ваша команда Петрович-ТЕХ</i>"
        )
        
        return message
    
    @staticmethod
    def format_maintenance_extended_message(
        description: str,
        new_end_time: datetime
    ) -> str:
        """
        Форматирует сообщение о продлении работ.
        
        Args:
            description: Описание работ
            new_end_time: Новое время окончания
        
        Returns:
            Отформатированное сообщение
        """
        new_end_time_str = new_end_time.strftime(DATETIME_FORMAT) if isinstance(new_end_time, datetime) else new_end_time
        
        message = (
            f"🔄 <b>Работа продлена</b>\n"
            f"• <b>Описание:</b> {description}\n"
            f"• <b>Новое время окончания:</b> {new_end_time_str}"
        )
        
        return message
    
    @staticmethod
    def format_maintenance_closed_message(description: str) -> str:
        """
        Форматирует сообщение о закрытии работ.
        
        Args:
            description: Описание работ
        
        Returns:
            Отформатированное сообщение
        """
        return (
            f"✅ <b>Работа завершена</b>\n"
            f"• <b>Описание:</b> {description}"
        )
    
    @staticmethod
    def format_regular_message(text: str) -> str:
        """
        Форматирует обычное сообщение.
        
        Args:
            text: Текст сообщения
        
        Returns:
            Отформатированное сообщение
        """
        return f"💬 <b>Сообщение от администратора:</b>\n{text}\n"

