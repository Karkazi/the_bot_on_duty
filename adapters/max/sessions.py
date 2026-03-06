# adapters/max/sessions.py — сессии сценария «Сообщить» и «Управлять» в MAX (по user_id)

from typing import Dict, Any, Optional

# user_id (MAX) -> {"step": str, "data": dict} — сценарий «Сообщить»
_sessions: Dict[int, Dict[str, Any]] = {}

# user_id (MAX) -> {"step": str, "item_id": str|None, "item_type": str|None} — сценарий «Управлять»
_manage_sessions: Dict[int, Dict[str, Any]] = {}

# user_id (MAX) -> message_id последнего сообщения бота (для удаления после ответа пользователя)
_last_bot_message_ids: Dict[int, str] = {}


def get_session(user_id: int) -> Dict[str, Any] | None:
    return _sessions.get(user_id)


def set_session(user_id: int, step: str, data: Dict[str, Any] | None = None) -> None:
    if data is None:
        data = _sessions.get(user_id, {}).get("data", {})
    _sessions[user_id] = {"step": step, "data": data}


def update_session_data(user_id: int, **kwargs: Any) -> None:
    if user_id not in _sessions:
        _sessions[user_id] = {"step": "", "data": {}}
    _sessions[user_id].setdefault("data", {}).update(kwargs)


def clear_session(user_id: int) -> None:
    _sessions.pop(user_id, None)
    _last_bot_message_ids.pop(user_id, None)


def get_last_bot_message_id(user_id: int) -> Optional[str]:
    """ID последнего сообщения бота в чате пользователя (для удаления после ответа)."""
    return _last_bot_message_ids.get(user_id)


def set_last_bot_message_id(user_id: int, message_id: str) -> None:
    _last_bot_message_ids[user_id] = message_id


def clear_last_bot_message_id(user_id: int) -> None:
    _last_bot_message_ids.pop(user_id, None)


def get_manage_session(user_id: int) -> Dict[str, Any] | None:
    return _manage_sessions.get(user_id)


def set_manage_session(user_id: int, step: str, item_id: str | None = None, item_type: str | None = None) -> None:
    _manage_sessions[user_id] = {
        "step": step,
        "item_id": item_id,
        "item_type": item_type or (_manage_sessions.get(user_id) or {}).get("item_type"),
    }


def clear_manage_session(user_id: int) -> None:
    _manage_sessions.pop(user_id, None)
