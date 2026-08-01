import json
import os
from datetime import datetime, timezone
from pathlib import Path


BASELINE_PATH = Path("/app/data/vm_inventory.json")
SCHEMA_VERSION = 1


def load_vm_baseline():
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


def build_vm_inventory(vm_list):
    return {
        vm["id"]: {
            "vm_name": vm.get("name", "Unknown VM"),
            "power_state": vm.get("power_state"),
            "esxi_host": vm.get("esxi_host", "--"),
        }
        for vm in vm_list
        if isinstance(vm, dict) and vm.get("id")
    }


def save_vm_baseline(inventory):
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


def power_state_events(previous_inventory, current_inventory, timestamp):
    events = []
    for vm_id in previous_inventory.keys() & current_inventory.keys():
        previous_vm = previous_inventory[vm_id]
        current_vm = current_inventory[vm_id]
        transition = (previous_vm.get("power_state"), current_vm.get("power_state"))
        if transition == ("poweredOff", "poweredOn"):
            event_type = "powered_on"
        elif transition == ("poweredOn", "poweredOff"):
            event_type = "powered_off"
        else:
            continue
        events.append({
            "event_type": event_type,
            "vm_id": vm_id,
            "vm_name": current_vm.get("vm_name", "Unknown VM"),
            "esxi_host": current_vm.get("esxi_host", "--"),
            "timestamp": timestamp,
        })
    return events
