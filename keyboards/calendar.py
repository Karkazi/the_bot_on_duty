"""
Клавиатуры календаря для выбора даты и времени.
Содержит клавиатуры для выбора месяца, дня, часа и минуты.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def create_month_keyboard(year: int, field_prefix: str = "start") -> InlineKeyboardMarkup:
    """Клавиатура выбора месяца"""
    builder = InlineKeyboardBuilder()
    months = [
        ("Янв", 1), ("Фев", 2), ("Мар", 3), ("Апр", 4),
        ("Май", 5), ("Июн", 6), ("Июл", 7), ("Авг", 8),
        ("Сен", 9), ("Окт", 10), ("Ноя", 11), ("Дек", 12)
    ]
    for i in range(0, len(months), 3):
        row = [InlineKeyboardButton(text=m[0], callback_data=f"cal_month_{field_prefix}_{year}_{m[1]}") 
               for m in months[i:i+3]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()


def create_day_keyboard(year: int, month: int, field_prefix: str = "start") -> InlineKeyboardMarkup:
    """Клавиатура выбора дня"""
    from calendar import monthrange
    days_in_month = monthrange(year, month)[1]
    builder = InlineKeyboardBuilder()
    
    # Создаем кнопки для дней месяца (по 7 в ряд для удобства)
    for week_start in range(1, days_in_month + 1, 7):
        week_days = []
        for day in range(week_start, min(week_start + 7, days_in_month + 1)):
            week_days.append(InlineKeyboardButton(
                text=str(day),
                callback_data=f"cal_day_{field_prefix}_{year}_{month}_{day}"
            ))
        if week_days:
            builder.row(*week_days)
    
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()


def create_hour_keyboard(field_prefix: str = "start") -> InlineKeyboardMarkup:
    """Клавиатура выбора часа (0-23)"""
    builder = InlineKeyboardBuilder()
    for i in range(0, 24, 4):
        row = [InlineKeyboardButton(text=f"{h:02d}", callback_data=f"cal_hour_{field_prefix}_{h}") 
               for h in range(i, min(i+4, 24))]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()


def create_minute_keyboard(field_prefix: str = "start") -> InlineKeyboardMarkup:
    """Клавиатура выбора минуты (0, 15, 30, 45)"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="00", callback_data=f"cal_minute_{field_prefix}_0"),
        InlineKeyboardButton(text="15", callback_data=f"cal_minute_{field_prefix}_15"),
        InlineKeyboardButton(text="30", callback_data=f"cal_minute_{field_prefix}_30"),
        InlineKeyboardButton(text="45", callback_data=f"cal_minute_{field_prefix}_45")
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"))
    return builder.as_markup()
