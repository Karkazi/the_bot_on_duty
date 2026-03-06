"""
Модуль клавиатур для бота.

Правило: весь используемый код клавиатур живёт в пакете keyboards/ по сценариям:
- main — главное меню, тип сообщения, отмена, да/нет, подтверждение;
- alarm — уровень, сервис, Jira/SCM/Петлокал;
- maintenance — выбор времени, спиннеры, продление;
- calendar — месяц, день, час, минута;
- manage — действия, продление, выбор сбоя/работы, напоминания, список событий.

Корневой файл keyboards.py в проекте не используется (при импорте «from keyboards» 
загружается этот пакет). Новые клавиатуры добавлять в соответствующий модуль пакета.
"""
# Импортируем все функции из модулей для обратной совместимости
from .main import (
    create_main_keyboard,
    create_message_type_keyboard,
    create_cancel_keyboard,
    create_yes_no_keyboard,
    create_confirmation_keyboard,
)
from .alarm import (
    create_level_keyboard,
    create_service_keyboard,
    create_jira_option_keyboard,
    create_scm_option_keyboard,
)
from .maintenance import (
    create_maintenance_time_selection_keyboard,
    create_maintenance_extend_time_selection_keyboard,
    create_time_spinner_keyboard,
    create_spinner_progress_bar,
    create_extend_time_spinner_keyboard,
)
from .calendar import (
    create_month_keyboard,
    create_day_keyboard,
    create_hour_keyboard,
    create_minute_keyboard,
)
from .manage import (
    create_action_keyboard,
    create_extension_time_keyboard,
    create_alarm_selection_keyboard,
    create_maintenance_selection_keyboard,
    create_stop_type_keyboard,
    create_reminder_keyboard,
    create_maintenance_reminder_keyboard,
    create_event_list_keyboard,
    create_refresh_keyboard,
)

# Экспортируем все функции
__all__ = [
    # Main
    "create_main_keyboard",
    "create_message_type_keyboard",
    "create_cancel_keyboard",
    "create_yes_no_keyboard",
    "create_confirmation_keyboard",
    # Alarm
    "create_level_keyboard",
    "create_service_keyboard",
    "create_jira_option_keyboard",
    "create_scm_option_keyboard",
    # Maintenance
    "create_maintenance_time_selection_keyboard",
    "create_maintenance_extend_time_selection_keyboard",
    "create_time_spinner_keyboard",
    "create_spinner_progress_bar",
    "create_extend_time_spinner_keyboard",
    # Calendar
    "create_month_keyboard",
    "create_day_keyboard",
    "create_hour_keyboard",
    "create_minute_keyboard",
    # Manage
    "create_action_keyboard",
    "create_extension_time_keyboard",
    "create_alarm_selection_keyboard",
    "create_maintenance_selection_keyboard",
    "create_stop_type_keyboard",
    "create_reminder_keyboard",
    "create_maintenance_reminder_keyboard",
    "create_event_list_keyboard",
    "create_refresh_keyboard",
]
