import json
import os
from datetime import datetime, timezone
from pathlib import Path


BASELINE_PATH = Path("/app/data/snapshot_inventory.json")
SCHEMA_VERSION = 1


def load_snapshot_baseline():
    try:
        with BASELINE_PATH.open("r", encoding="utf-8") as baseline_file:
            baseline = json.load(baseline_file)
    except (OSError, json.JSONDecodeError):
        return None

    if (
        not isinstance(baseline, dict)
        or baseline.get("version") != SCHEMA_VERSION
        or not isinstance(baseline.get("vms"), dict)
    ):
        return None
    return baseline["vms"]


def save_snapshot_baseline(inventory):
    baseline = {
        "version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "vms": inventory,
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = BASELINE_PATH.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as baseline_file:
        json.dump(baseline, baseline_file, indent=2, sort_keys=True)
        baseline_file.flush()
        os.fsync(baseline_file.fileno())
    os.replace(temporary_path, BASELINE_PATH)


def snapshot_events(previous_inventory, current_inventory):
    events = []
    for vm_id in previous_inventory.keys() & current_inventory.keys():
        previous_vm = previous_inventory[vm_id]
        current_vm = current_inventory[vm_id]
        previous_snapshots = previous_vm.get("snapshots", {})
        current_snapshots = current_vm.get("snapshots", {})
        if not isinstance(previous_snapshots, dict) or not isinstance(current_snapshots, dict):
            continue

        for snapshot_id in current_snapshots.keys() - previous_snapshots.keys():
            events.append({
                "event_type": "snapshot_created",
                "vm_id": vm_id,
                "vm_name": current_vm.get("vm_name", "Unknown VM"),
                "snapshot": current_snapshots[snapshot_id],
            })
        for snapshot_id in previous_snapshots.keys() - current_snapshots.keys():
            events.append({
                "event_type": "snapshot_deleted",
                "vm_id": vm_id,
                "vm_name": previous_vm.get("vm_name", "Unknown VM"),
                "snapshot": previous_snapshots[snapshot_id],
            })
    return events
