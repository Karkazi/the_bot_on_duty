from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from utils.app_paths import APP_DATA_DIR

logger = logging.getLogger(__name__)


HISTORY_FILE = APP_DATA_DIR / "alarm_history.jsonl"


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0, 0))
    end_exclusive = start + timedelta(days=1)
    return start, end_exclusive


@dataclass(frozen=True)
class AlarmHistoryRow:
    kind: str  # "alarm_created" | "alarm_closed"
    alarm_id: str
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    service: Optional[str] = None
    service_other_spec: Optional[str] = None
    jira_key: Optional[str] = None
    issue: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "alarm_id": self.alarm_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "service": self.service,
            "service_other_spec": self.service_other_spec,
            "jira_key": self.jira_key,
            "issue": self.issue,
        }


def append_alarm_created(*, alarm_id: str, alarm_info: dict) -> None:
    row = AlarmHistoryRow(
        kind="alarm_created",
        alarm_id=alarm_id,
        created_at=_parse_dt(alarm_info.get("created_at")),
        service=(alarm_info.get("service") or None),
        service_other_spec=(alarm_info.get("service_other_spec") or None),
        jira_key=(alarm_info.get("jira_key") or None),
        issue=(alarm_info.get("issue") or None),
    )
    _append_row(row)


def append_alarm_closed(*, alarm_id: str, alarm_info: dict, closed_at: datetime) -> None:
    row = AlarmHistoryRow(
        kind="alarm_closed",
        alarm_id=alarm_id,
        created_at=_parse_dt(alarm_info.get("created_at")),
        closed_at=closed_at,
        service=(alarm_info.get("service") or None),
        service_other_spec=(alarm_info.get("service_other_spec") or None),
        jira_key=(alarm_info.get("jira_key") or None),
        issue=(alarm_info.get("issue") or None),
    )
    _append_row(row)


def _append_row(row: AlarmHistoryRow) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row.to_json(), ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("[HISTORY] Не удалось записать историю сбоев: %s", e, exc_info=True)


def iter_rows() -> Iterable[AlarmHistoryRow]:
    if not HISTORY_FILE.is_file():
        return []
    rows: list[AlarmHistoryRow] = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    rows.append(
                        AlarmHistoryRow(
                            kind=str(obj.get("kind") or ""),
                            alarm_id=str(obj.get("alarm_id") or ""),
                            created_at=_parse_dt(obj.get("created_at")),
                            closed_at=_parse_dt(obj.get("closed_at")),
                            service=(obj.get("service") or None),
                            service_other_spec=(obj.get("service_other_spec") or None),
                            jira_key=(obj.get("jira_key") or None),
                            issue=(obj.get("issue") or None),
                        )
                    )
                except Exception:
                    continue
    except Exception as e:
        logger.warning("[HISTORY] Не удалось прочитать историю сбоев: %s", e, exc_info=True)
        return []
    return rows


def build_alarm_stats_report(*, start: date, end: date) -> str:
    """
    Статистика по сбоям за период [start..end] (включительно) по дате создания.
    """
    start_dt, _ = _day_bounds(start)
    _, end_excl = _day_bounds(end)

    created_rows = [
        r
        for r in iter_rows()
        if r.kind == "alarm_created" and r.created_at and start_dt <= r.created_at < end_excl
    ]

    total = len(created_rows)
    if total == 0:
        return f"📊 Сбои за {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n\nНет данных."

    by_service: dict[str, int] = {}
    other_specs: dict[str, int] = {}

    for r in created_rows:
        svc = (r.service or "не указано").strip() or "не указано"
        by_service[svc] = by_service.get(svc, 0) + 1
        if svc.lower() == "другое":
            spec = (r.service_other_spec or "").strip() or "не указано"
            other_specs[spec] = other_specs.get(spec, 0) + 1

    lines = [
        f"📊 Сбои за {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}",
        "",
        f"Всего: {total}",
        "",
        "По сервисам:",
    ]

    for svc, cnt in sorted(by_service.items(), key=lambda x: (-x[1], x[0].lower())):
        lines.append(f"• {svc} — {cnt}")

    if other_specs:
        lines.append("")
        lines.append("Другое (уточнения):")
        for spec, cnt in sorted(other_specs.items(), key=lambda x: (-x[1], x[0].lower())):
            lines.append(f"— {spec} ({cnt})")

    return "\n".join(lines)

