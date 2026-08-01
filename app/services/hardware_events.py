import json
import os
from datetime import datetime, timezone
from pathlib import Path


BASELINE_PATH = Path("/app/data/hardware_inventory.json")
SCHEMA_VERSION = 1


def load_hardware_baseline():
    try:
        with BASELINE_PATH.open("r", encoding="utf-8") as baseline_file:
            baseline = json.load(baseline_file)
    except (OSError, json.JSONDecodeError):
        return None

    if (
        not isinstance(baseline, dict)
        or baseline.get("version") != SCHEMA_VERSION
        or not isinstance(baseline.get("host"), dict)
        or not isinstance(baseline.get("ilo"), dict)
    ):
        return None
    return {"host": baseline["host"], "ilo": baseline["ilo"]}


def build_hardware_inventory(summary, ilo_health):
    return {
        "host": {
            "host_name": summary.get("host_name", "Unknown host"),
            "status": summary.get("status", "unavailable"),
        },
        "ilo": {
            "status": ilo_health.get("status", "Unavailable"),
            "fan": dict(ilo_health.get("fan", {})),
            "psu": dict(ilo_health.get("psu", {})),
            "temperature": {
                "cpu": ilo_health.get("temperature", {}).get("cpu"),
                "ambient": ilo_health.get("temperature", {}).get("ambient"),
            },
        },
    }


def save_hardware_baseline(inventory):
    baseline = {
        "version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **inventory,
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = BASELINE_PATH.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as baseline_file:
        json.dump(baseline, baseline_file, indent=2, sort_keys=True)
        baseline_file.flush()
        os.fsync(baseline_file.fileno())
    os.replace(temporary_path, BASELINE_PATH)


def _is_ok(status):
    return status == "OK"


def _is_online(status):
    return status == "online"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def hardware_events(previous, current, threshold, timestamp):
    events = []
    previous_host = previous["host"]
    current_host = current["host"]
    if _is_online(previous_host.get("status")) and not _is_online(current_host.get("status")):
        events.append({"event_type": "host_offline", "host": current_host["host_name"], "timestamp": timestamp})
    elif not _is_online(previous_host.get("status")) and _is_online(current_host.get("status")):
        events.append({"event_type": "host_online", "host": current_host["host_name"], "timestamp": timestamp})

    previous_ilo = previous["ilo"]
    current_ilo = current["ilo"]
    for field, prefix in (("status", "ilo_health"), ("fan", "fan_status"), ("psu", "psu_status")):
        previous_status = previous_ilo.get(field) if field == "status" else previous_ilo.get(field, {}).get("status")
        current_status = current_ilo.get(field) if field == "status" else current_ilo.get(field, {}).get("status")
        if _is_ok(previous_status) and not _is_ok(current_status):
            event_type = f"{prefix}_degraded"
        elif not _is_ok(previous_status) and _is_ok(current_status):
            event_type = f"{prefix}_recovered"
        else:
            continue
        event = {"event_type": event_type, "host": current_host["host_name"], "status": current_status, "timestamp": timestamp}
        if field in {"fan", "psu"}:
            event["count"] = current_ilo.get(field, {}).get("count")
        events.append(event)

    previous_temperature = previous_ilo.get("temperature", {})
    current_temperature = current_ilo.get("temperature", {})
    previous_cpu = previous_temperature.get("cpu")
    current_cpu = current_temperature.get("cpu")
    if _number(previous_cpu) and _number(current_cpu):
        if previous_cpu < threshold <= current_cpu:
            event_type = "temperature_alert"
        elif previous_cpu >= threshold > current_cpu:
            event_type = "temperature_recovered"
        else:
            event_type = None
        if event_type:
            events.append({
                "event_type": event_type,
                "host": current_host["host_name"],
                "cpu": current_cpu,
                "ambient": current_temperature.get("ambient"),
                "threshold": threshold,
                "timestamp": timestamp,
            })
    return events
