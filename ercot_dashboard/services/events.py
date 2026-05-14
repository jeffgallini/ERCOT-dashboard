from __future__ import annotations

from threading import RLock
from typing import Any
from uuid import uuid4

from ercot_dashboard.services.clients import utc_now


VALID_EVENT_LEVELS = {"info", "success", "warning", "danger"}
MAX_OPERATOR_EVENTS = 25

_EVENTS: dict[str, dict[str, Any]] = {}
_LOCK = RLock()


def list_operator_events(*, limit: int = MAX_OPERATOR_EVENTS, include_acknowledged: bool = True) -> list[dict[str, Any]]:
    with _LOCK:
        events = [dict(event) for event in _EVENTS.values()]

    if not include_acknowledged:
        events = [event for event in events if not event.get("acknowledged")]

    events.sort(key=lambda event: str(event.get("updated_at") or event.get("timestamp") or ""), reverse=True)
    return events[:limit]


def create_operator_event(payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    event_id = f"evt-{uuid4().hex[:10]}"
    event = {
        "id": event_id,
        "timestamp": now.isoformat(),
        "updated_at": now.isoformat(),
        "time": now.strftime("%H:%M:%S UTC"),
        "level": _normalize_level(payload.get("level")),
        "title": _clean_text(payload.get("title"), fallback="Operator event"),
        "message": _clean_text(payload.get("message"), fallback="Manual operator note."),
        "source": _clean_text(payload.get("source"), fallback="Operator"),
        "acknowledged": bool(payload.get("acknowledged", False)),
    }
    if event["acknowledged"]:
        event["acknowledged_at"] = now.isoformat()

    with _LOCK:
        _EVENTS[event_id] = event
        _trim_events()

    return dict(event)


def update_operator_event(event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        if event_id not in _EVENTS:
            raise KeyError(event_id)

        now = utc_now()
        event = dict(_EVENTS[event_id])
        for key in ("title", "message", "source"):
            if key in payload and payload[key] is not None:
                event[key] = _clean_text(payload[key], fallback=event[key])
        if "level" in payload and payload["level"] is not None:
            event["level"] = _normalize_level(payload["level"])
        if "acknowledged" in payload and payload["acknowledged"] is not None:
            acknowledged = bool(payload["acknowledged"])
            event["acknowledged"] = acknowledged
            if acknowledged:
                event["acknowledged_at"] = now.isoformat()
            else:
                event.pop("acknowledged_at", None)

        event["updated_at"] = now.isoformat()
        event["time"] = now.strftime("%H:%M:%S UTC")
        _EVENTS[event_id] = event
        return dict(event)


def delete_operator_event(event_id: str) -> dict[str, Any]:
    with _LOCK:
        if event_id not in _EVENTS:
            raise KeyError(event_id)
        return dict(_EVENTS.pop(event_id))


def clear_operator_events() -> None:
    with _LOCK:
        _EVENTS.clear()


def _trim_events() -> None:
    if len(_EVENTS) <= MAX_OPERATOR_EVENTS:
        return

    ordered = sorted(_EVENTS.values(), key=lambda event: str(event.get("updated_at") or ""), reverse=True)
    retained_ids = {str(event["id"]) for event in ordered[:MAX_OPERATOR_EVENTS]}
    for event_id in list(_EVENTS):
        if event_id not in retained_ids:
            _EVENTS.pop(event_id, None)


def _normalize_level(value: Any) -> str:
    level = str(value or "info").lower().strip()
    return level if level in VALID_EVENT_LEVELS else "info"


def _clean_text(value: Any, *, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback
