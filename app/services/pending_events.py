import copy
import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


EVENTS_PATH = Path("/app/data/pending_events.json")
LOCK_PATH = Path("/app/data/pending_events.lock")
SCHEMA_VERSION = 1
PENDING_TTL = timedelta(hours=24)
TERMINAL_TTL = timedelta(days=7)


def _now():
    return datetime.now(timezone.utc)


def _timestamp():
    return _now().isoformat()


def _parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@contextmanager
def _event_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_unlocked():
    try:
        with EVENTS_PATH.open("r", encoding="utf-8") as event_file:
            queue = json.load(event_file)
    except (OSError, json.JSONDecodeError):
        return {"version": SCHEMA_VERSION, "events": {}}
    if (
        not isinstance(queue, dict)
        or queue.get("version") != SCHEMA_VERSION
        or not isinstance(queue.get("events"), dict)
    ):
        return {"version": SCHEMA_VERSION, "events": {}}
    return queue


def _save_unlocked(queue):
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = EVENTS_PATH.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as event_file:
        json.dump(queue, event_file, indent=2, sort_keys=True)
        event_file.flush()
        os.fsync(event_file.fileno())
    os.replace(temporary_path, EVENTS_PATH)


def _cleanup_unlocked(queue):
    now = _now()
    changed = False
    for operation_id, event in list(queue["events"].items()):
        if not isinstance(event, dict):
            del queue["events"][operation_id]
            changed = True
            continue
        status = event.get("status")
        requested_at = _parse_timestamp(event.get("requested_at"))
        if status in {"accepted", "queued", "running"}:
            if requested_at and now - requested_at > PENDING_TTL:
                event["status"] = "expired"
                event["expired_at"] = _timestamp()
                changed = True
            continue
        terminal_at = _parse_timestamp(
            event.get("completed_at")
            or event.get("failed_at")
            or event.get("expired_at")
        )
        if terminal_at and now - terminal_at > TERMINAL_TTL:
            del queue["events"][operation_id]
            changed = True
    return changed


def create_pending_event(event_type, task, source):
    if event_type != "vm_reset":
        raise ValueError("Unsupported pending event type")
    source = "telegram" if source == "telegram" else "dashboard"
    operation_id = str(uuid.uuid4())
    event = {
        "operation_id": operation_id,
        "event_type": event_type,
        "status": "accepted",
        "task_id": task["id"],
        "vm_id": task["vm_id"],
        "vm_name": task["vm_name"],
        "source": source,
        "requested_at": _timestamp(),
        "completed_at": None,
        "failed_at": None,
        "notified": False,
        "notified_at": None,
        "delivery_result": None,
    }
    with _event_lock():
        queue = _load_unlocked()
        _cleanup_unlocked(queue)
        queue["events"][operation_id] = event
        _save_unlocked(queue)
    return copy.deepcopy(event)


def load_pending_events():
    with _event_lock():
        queue = _load_unlocked()
        if _cleanup_unlocked(queue):
            _save_unlocked(queue)
        return copy.deepcopy(list(queue["events"].values()))


def update_pending_event(operation_id, **changes):
    with _event_lock():
        queue = _load_unlocked()
        _cleanup_unlocked(queue)
        event = queue["events"].get(operation_id)
        if not isinstance(event, dict):
            return None
        event.update(changes)
        _save_unlocked(queue)
        return copy.deepcopy(event)


def claim_notification(operation_id, delivery_result=None):
    with _event_lock():
        queue = _load_unlocked()
        _cleanup_unlocked(queue)
        event = queue["events"].get(operation_id)
        if (
            not isinstance(event, dict)
            or event.get("status") != "completed"
            or event.get("notified")
        ):
            return None
        event["notified"] = True
        event["notified_at"] = _timestamp()
        event["delivery_result"] = delivery_result
        _save_unlocked(queue)
        return copy.deepcopy(event)
