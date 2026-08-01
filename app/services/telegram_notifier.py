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


def send_snapshot_notification(event):
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        recipients = _allowed_user_ids()
        if not token or not recipients:
            return {"attempted": 0, "delivered": 0}

        message = _snapshot_message(event)
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
