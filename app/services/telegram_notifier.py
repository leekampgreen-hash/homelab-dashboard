import os

import requests


TELEGRAM_API_TIMEOUT = (3, 10)


def _allowed_user_ids():
    user_ids = set()
    for value in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(","):
        try:
            user_id = int(value.strip())
        except (TypeError, ValueError):
            continue
        user_ids.add(user_id)
    return user_ids


def _snapshot_message(event):
    snapshot = event["snapshot"]
    is_created = event["event_type"] == "snapshot_created"
    lines = [
        "📸 Snapshot Created" if is_created else "🗑️ Snapshot Deleted",
        "",
        f"VM: {event['vm_name']}",
        f"Snapshot: {snapshot.get('name', 'Unknown snapshot')}",
    ]
    if is_created and snapshot.get("created"):
        lines.append(f"Created: {str(snapshot['created']).replace('T', ' ')[:16]}")
    if snapshot.get("description"):
        lines.append(f"Description: {snapshot['description']}")
    return "\n".join(lines)


def _vm_message(event):
    is_powered_on = event["event_type"] == "powered_on"
    return "\n".join([
        "🟢 VM Powered On" if is_powered_on else "🔴 VM Powered Off",
        "",
        f"VM: {event['vm_name']}",
        f"Host: {event.get('esxi_host', '--')}",
        f"Time: {event['timestamp']}",
    ])


def _hardware_message(event):
    event_type = event["event_type"]
    timestamp = event["timestamp"]

    if event_type == "host_offline":
        lines = ["🔴 ESXi Host Offline", "", f"Host: {event['host']}"]
    elif event_type == "host_online":
        lines = ["🟢 ESXi Host Online", "", f"Host: {event['host']}"]
    elif event_type == "ilo_health_degraded":
        lines = ["⚠️ iLO Hardware Health", "", f"Status: {event['status']}"]
    elif event_type == "ilo_health_recovered":
        lines = ["🟢 iLO Hardware Health Recovered", "", "Status: OK"]
    elif event_type == "fan_status_degraded":
        lines = [
            "⚠️ Fan Status",
            "",
            f"Status: {event['status']}",
            f"Count: {event['count']}",
        ]
    elif event_type == "fan_status_recovered":
        lines = [
            "🟢 Fan Status Recovered",
            "",
            "Status: OK",
            f"Count: {event['count']}",
        ]
    elif event_type == "psu_status_degraded":
        lines = [
            "⚠️ PSU Status",
            "",
            f"Status: {event['status']}",
            f"Count: {event['count']}",
        ]
    elif event_type == "psu_status_recovered":
        lines = [
            "🟢 PSU Status Recovered",
            "",
            "Status: OK",
            f"Count: {event['count']}",
        ]
    elif event_type == "temperature_alert":
        lines = ["🌡️ Temperature Alert", ""]
    elif event_type == "temperature_recovered":
        lines = ["🟢 Temperature Recovered", ""]
    else:
        raise ValueError("Unsupported hardware event")

    if event_type in {"temperature_alert", "temperature_recovered"}:
        ambient = event.get("ambient")
        lines.extend([
            f"CPU: {event['cpu']}°C",
            f"Ambient: {ambient}°C" if ambient is not None else "Ambient: --",
            f"Threshold: {event['threshold']}°C",
        ])
    elif event_type in {
        "fan_status_degraded",
        "fan_status_recovered",
        "psu_status_degraded",
        "psu_status_recovered",
    }:
        lines[-1] = (
            f"Count: {event['count']}"
            if event.get("count") is not None and event.get("status") != "Unavailable"
            else "Count: --"
        )
    lines.append(f"Time: {timestamp}")
    return "\n".join(lines)


def _format_free_space(free_bytes):
    if not isinstance(free_bytes, (int, float)) or isinstance(free_bytes, bool):
        return "--"
    gigabyte = 1024 ** 3
    terabyte = 1024 ** 4
    if free_bytes >= terabyte:
        return f"{free_bytes / terabyte:.1f} TB"
    return f"{free_bytes / gigabyte:.1f} GB"


def _datastore_message(event):
    recovered = event["event_type"] == "datastore_usage_recovered"
    return "\n".join([
        "🟢 Datastore Usage Recovered" if recovered else "⚠️ Datastore Usage Alert",
        "",
        f"Datastore: {event['datastore_name']}",
        f"Usage: {event['usage_percent']}%",
        f"Threshold: {event['threshold']}%",
        f"Free: {_format_free_space(event.get('free_bytes'))}",
        f"Time: {event['timestamp']}",
    ])


def _send_message(message):
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        recipients = _allowed_user_ids()
        if not token or not recipients:
            return {"attempted": 0, "delivered": 0}

        delivered = 0
        for user_id in recipients:
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": user_id, "text": message},
                    timeout=TELEGRAM_API_TIMEOUT,
                )
                if response.ok:
                    delivered += 1
            except Exception:
                continue
        return {"attempted": len(recipients), "delivered": delivered}
    except Exception:
        return {"attempted": 0, "delivered": 0}


def send_snapshot_notification(event):
    try:
        return _send_message(_snapshot_message(event))
    except Exception:
        return {"attempted": 0, "delivered": 0}


def send_vm_notification(event):
    try:
        return _send_message(_vm_message(event))
    except Exception:
        return {"attempted": 0, "delivered": 0}


def send_hardware_notification(event):
    try:
        return _send_message(_hardware_message(event))
    except Exception:
        return {"attempted": 0, "delivered": 0}


def send_datastore_notification(event):
    try:
        return _send_message(_datastore_message(event))
    except Exception:
        return {"attempted": 0, "delivered": 0}
