import json
import os
from datetime import datetime, timezone
from pathlib import Path


BASELINE_PATH = Path("/app/data/datastore_inventory.json")
SCHEMA_VERSION = 1


def load_datastore_baseline():
    try:
        with BASELINE_PATH.open("r", encoding="utf-8") as baseline_file:
            baseline = json.load(baseline_file)
    except (OSError, json.JSONDecodeError):
        return None

    if (
        not isinstance(baseline, dict)
        or baseline.get("version") != SCHEMA_VERSION
        or not isinstance(baseline.get("datastores"), dict)
    ):
        return None
    return baseline["datastores"]


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_datastore_inventory(datastores):
    inventory = {}
    for datastore in datastores or []:
        if not isinstance(datastore, dict):
            continue
        datastore_id = datastore.get("id")
        usage_percent = datastore.get("usage_percent")
        if not datastore_id or not _number(usage_percent):
            continue
        inventory[datastore_id] = {
            "name": datastore.get("name") or datastore_id,
            "usage_percent": usage_percent,
            "free_bytes": datastore.get("free_bytes"),
        }
    return inventory


def save_datastore_baseline(inventory):
    baseline = {
        "version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "datastores": inventory,
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = BASELINE_PATH.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as baseline_file:
        json.dump(baseline, baseline_file, indent=2, sort_keys=True)
        baseline_file.flush()
        os.fsync(baseline_file.fileno())
    os.replace(temporary_path, BASELINE_PATH)


def datastore_events(previous_inventory, current_inventory, threshold, timestamp):
    events = []
    for datastore_id in previous_inventory.keys() & current_inventory.keys():
        previous = previous_inventory[datastore_id]
        current = current_inventory[datastore_id]
        previous_usage = previous.get("usage_percent")
        current_usage = current.get("usage_percent")
        if not _number(previous_usage) or not _number(current_usage):
            continue
        if previous_usage < threshold <= current_usage:
            event_type = "datastore_usage_alert"
        elif previous_usage >= threshold > current_usage:
            event_type = "datastore_usage_recovered"
        else:
            continue
        events.append({
            "event_type": event_type,
            "datastore_id": datastore_id,
            "datastore_name": current.get("name", datastore_id),
            "usage_percent": current_usage,
            "free_bytes": current.get("free_bytes"),
            "threshold": threshold,
            "timestamp": timestamp,
        })
    return events
