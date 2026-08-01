import copy
import json
import os
from pathlib import Path


SETTINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "alert_settings.json"

DEFAULT_ALERT_SETTINGS = {
    "hardware": {
        "host_online": {"enabled": False},
        "ilo_health": {"enabled": False},
        "fan_status": {"enabled": False},
        "psu_status": {"enabled": False},
        "temperature": {"enabled": False, "threshold": 80},
        "datastore_usage": {"enabled": False, "threshold": 90},
    },
    "vm": {
        "powered_on": {"enabled": False},
        "powered_off": {"enabled": False},
        "reset": {"enabled": False},
        "snapshot_created": {"enabled": False},
        "snapshot_restored": {"enabled": False},
        "snapshot_deleted": {"enabled": False},
    },
}

THRESHOLD_LIMITS = {
    ("hardware", "temperature"): (1, 120),
    ("hardware", "datastore_usage"): (1, 100),
}


def load_alert_settings():
    settings = copy.deepcopy(DEFAULT_ALERT_SETTINGS)
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as settings_file:
            stored_settings = json.load(settings_file)
    except (OSError, json.JSONDecodeError):
        return settings

    if not isinstance(stored_settings, dict):
        return settings

    for category, alerts in settings.items():
        stored_alerts = stored_settings.get(category)
        if not isinstance(stored_alerts, dict):
            continue
        for alert_name, default_config in alerts.items():
            stored_config = stored_alerts.get(alert_name)
            if not isinstance(stored_config, dict):
                continue
            if isinstance(stored_config.get("enabled"), bool):
                default_config["enabled"] = stored_config["enabled"]
            if "threshold" in default_config:
                threshold = stored_config.get("threshold")
                minimum, maximum = THRESHOLD_LIMITS[(category, alert_name)]
                if isinstance(threshold, int) and minimum <= threshold <= maximum:
                    default_config["threshold"] = threshold
    return settings


def _write_alert_settings(settings):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = SETTINGS_PATH.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as settings_file:
        json.dump(settings, settings_file, indent=2, sort_keys=True)
        settings_file.flush()
        os.fsync(settings_file.fileno())
    os.replace(temporary_path, SETTINGS_PATH)


def set_alert_enabled(category, alert_name, enabled):
    settings = load_alert_settings()
    config = settings[category][alert_name]
    old_value = config["enabled"]
    config["enabled"] = bool(enabled)
    _write_alert_settings(settings)
    return old_value, config["enabled"]


def set_alert_threshold(category, alert_name, threshold):
    minimum, maximum = THRESHOLD_LIMITS[(category, alert_name)]
    if not isinstance(threshold, int) or not minimum <= threshold <= maximum:
        raise ValueError("Invalid alert threshold")
    settings = load_alert_settings()
    config = settings[category][alert_name]
    old_value = config["threshold"]
    config["threshold"] = threshold
    _write_alert_settings(settings)
    return old_value, threshold
