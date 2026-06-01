# utils/helpers.py
from datetime import timedelta
import re
from typing import Optional

def parse_duration(duration_str: str) -> Optional[timedelta]:
    duration_str = duration_str.lower().strip()
    pattern = r'(\d+[\.,]?\d*)\s*(минут[аы]?|мин|час[аов]?|дн[яей])'
    match = re.search(pattern, duration_str)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2)
    if 'минут' in unit or 'мин' in unit:
        return timedelta(minutes=value)
    if 'час' in unit:
        return timedelta(hours=value)
    if 'дн' in unit:
        return timedelta(days=value)
    return None
