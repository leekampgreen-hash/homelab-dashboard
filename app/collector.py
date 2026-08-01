import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import ESXI_HOST
from services.cache import load_cache, save_cache
from services.logger import logger
from services.vmware import (
    get_host_summary,
    get_snapshot_inventory,
    get_task_status_by_id,
    get_vm_list,
)
from services.hardware import get_hardware_summary
from services.ilo import get_ilo_health
from services.alert_engine import generate_alerts
from services.alert_settings import load_alert_settings
from services.snapshot_events import (
    load_snapshot_baseline,
    save_snapshot_baseline,
    snapshot_events,
)
from services.telegram_notifier import (
    send_datastore_notification,
    send_hardware_notification,
    send_snapshot_notification,
    send_vm_reset_notification,
    send_vm_notification,
)
from services.pending_events import (
    claim_notification,
    load_pending_events,
    update_pending_event,
)
from services.hardware_events import (
    build_hardware_inventory,
    hardware_events,
    load_hardware_baseline,
    save_hardware_baseline,
)
from services.datastore_events import (
    build_datastore_inventory,
    datastore_events,
    load_datastore_baseline,
    save_datastore_baseline,
)
from services.vm_events import (
    build_vm_inventory,
    load_vm_baseline,
    power_state_events,
    save_vm_baseline,
)


def collect_subsystem(name, collector):
    try:
        result = collector()
        logger.info("%s collection succeeded", name)
        return result
    except Exception:
        logger.exception("%s collection failed", name)
        raise


def unavailable_ilo_health():
    return {
        "status": "Unavailable",
        "chassis": {"model": "Unavailable"},
        "fan": {"status": "Unavailable", "count": 0},
        "temperature": {"cpu": None, "ambient": None, "storage": None},
        "power": {"current": None, "average": None, "max": None},
        "psu": {"status": "Unavailable", "count": 0}
    }


def unavailable_host_summary():
    return {"host_name": ESXI_HOST, "status": "offline"}


def collect_optional_subsystem(name, collector, fallback):
    try:
        result = collector()
        logger.info("%s collection succeeded", name)
        return result
    except Exception as exc:
        logger.warning("%s collection unavailable: %s", name, exc)
        return fallback()


def collect_snapshot_events():
    try:
        current_inventory = get_snapshot_inventory()
    except Exception as exc:
        logger.warning("Snapshot inventory collection unavailable: %s", exc)
        return

    previous_inventory = load_snapshot_baseline()
    try:
        events = [] if previous_inventory is None else snapshot_events(
            previous_inventory, current_inventory
        )
        save_snapshot_baseline(current_inventory)
    except Exception as exc:
        logger.warning("Snapshot baseline update failed: %s", exc)
        return

    if previous_inventory is None:
        logger.info("Snapshot baseline established")
        return

    settings = load_alert_settings()
    for event in events:
        snapshot = event["snapshot"]
        event_type = event["event_type"]
        enabled = settings["vm"][event_type]["enabled"]
        delivery = {"attempted": 0, "delivered": 0}
        if enabled:
            delivery = send_snapshot_notification(event)
        logger.info(
            "Snapshot event type=%s vm_id=%s vm_name=%s snapshot_id=%s "
            "delivery_result=%s/%s",
            event_type,
            event["vm_id"],
            event["vm_name"],
            snapshot.get("id"),
            delivery["delivered"],
            delivery["attempted"],
        )


def collect_vm_power_events(vm_list, timestamp):
    current_inventory = build_vm_inventory(vm_list)
    previous_inventory = load_vm_baseline()
    try:
        events = [] if previous_inventory is None else power_state_events(
            previous_inventory, current_inventory, timestamp
        )
        save_vm_baseline(current_inventory)
    except Exception as exc:
        logger.warning("VM power-state baseline update failed: %s", exc)
        return

    if previous_inventory is None:
        logger.info("VM power-state baseline established")
        return

    settings = load_alert_settings()
    for event in events:
        delivery = {"attempted": 0, "delivered": 0}
        if settings["vm"][event["event_type"]]["enabled"]:
            delivery = send_vm_notification(event)
        logger.info(
            "VM power event type=%s vm_id=%s vm_name=%s esxi_host=%s "
            "delivery_result=%s/%s",
            event["event_type"],
            event["vm_id"],
            event["vm_name"],
            event["esxi_host"],
            delivery["delivered"],
            delivery["attempted"],
        )


def collect_hardware_events(summary, ilo_health, timestamp):
    try:
        settings = load_alert_settings()
        current_inventory = build_hardware_inventory(summary, ilo_health)
        previous_inventory = load_hardware_baseline()
        events = [] if previous_inventory is None else hardware_events(
            previous_inventory,
            current_inventory,
            settings["hardware"]["temperature"]["threshold"],
            timestamp,
        )
        save_hardware_baseline(current_inventory)
    except Exception as exc:
        logger.warning("Hardware event baseline update failed: %s", exc)
        return

    if previous_inventory is None:
        logger.info("Hardware event baseline established")
        return

    setting_by_event = {
        "host_offline": "host_online",
        "host_online": "host_online",
        "ilo_health_degraded": "ilo_health",
        "ilo_health_recovered": "ilo_health",
        "fan_status_degraded": "fan_status",
        "fan_status_recovered": "fan_status",
        "psu_status_degraded": "psu_status",
        "psu_status_recovered": "psu_status",
        "temperature_alert": "temperature",
        "temperature_recovered": "temperature",
    }
    for event in events:
        delivery = {"attempted": 0, "delivered": 0}
        if settings["hardware"][setting_by_event[event["event_type"]]]["enabled"]:
            delivery = send_hardware_notification(event)
        logger.info(
            "Hardware event type=%s host=%s status=%s delivery_result=%s/%s",
            event["event_type"],
            event["host"],
            event.get("status", "normal"),
            delivery["delivered"],
            delivery["attempted"],
        )


def collect_datastore_events(summary, timestamp):
    try:
        settings = load_alert_settings()
        current_inventory = build_datastore_inventory(summary.get("datastores"))
        if not current_inventory:
            logger.warning("Datastore inventory unavailable or empty; baseline preserved")
            return
        previous_inventory = load_datastore_baseline()
        events = [] if previous_inventory is None else datastore_events(
            previous_inventory,
            current_inventory,
            settings["hardware"]["datastore_usage"]["threshold"],
            timestamp,
        )
        save_datastore_baseline(current_inventory)
    except Exception as exc:
        logger.warning("Datastore baseline update failed: %s", exc)
        return

    if previous_inventory is None:
        logger.info("Datastore baseline established")
        return

    for event in events:
        delivery = {"attempted": 0, "delivered": 0}
        if settings["hardware"]["datastore_usage"]["enabled"]:
            delivery = send_datastore_notification(event)
        logger.info(
            "Datastore event type=%s datastore_id=%s datastore_name=%s "
            "usage=%s threshold=%s delivery_result=%s/%s",
            event["event_type"],
            event["datastore_id"],
            event["datastore_name"],
            event["usage_percent"],
            event["threshold"],
            delivery["delivered"],
            delivery["attempted"],
        )


def collect_pending_events():
    settings = load_alert_settings()
    for event in load_pending_events():
        if event.get("event_type") != "vm_reset":
            continue

        operation_id = event.get("operation_id")
        status = event.get("status")
        if not operation_id:
            continue

        if status in {"accepted", "queued", "running"}:
            try:
                task = get_task_status_by_id(event.get("task_id"))
            except Exception:
                logger.warning(
                    "Pending event task unavailable operation_id=%s event_type=%s "
                    "vm_id=%s vm_name=%s source=%s status=%s",
                    operation_id,
                    event.get("event_type"),
                    event.get("vm_id"),
                    event.get("vm_name"),
                    event.get("source"),
                    status,
                )
                continue

            task_state = task.get("state")
            if task_state in {"queued", "running"}:
                event = update_pending_event(operation_id, status=task_state) or event
            elif task_state == "success":
                completed_at = task.get("complete_time")
                if isinstance(completed_at, str):
                    try:
                        datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                    except ValueError:
                        completed_at = None
                else:
                    completed_at = None
                event = update_pending_event(
                    operation_id,
                    status="completed",
                    completed_at=completed_at or datetime.now(timezone.utc).isoformat(),
                ) or event
            elif task_state in {"error", "cancelled"}:
                event = update_pending_event(
                    operation_id,
                    status="failed",
                    failed_at=datetime.now(timezone.utc).isoformat(),
                ) or event

        if event.get("status") != "completed" or event.get("notified"):
            continue

        if not settings["vm"]["reset"]["enabled"]:
            claimed_event = claim_notification(operation_id, "disabled")
            if claimed_event:
                logger.info(
                    "Pending event operation_id=%s event_type=%s vm_id=%s "
                    "vm_name=%s source=%s status=%s delivery_result=%s",
                    operation_id,
                    claimed_event["event_type"],
                    claimed_event["vm_id"],
                    claimed_event["vm_name"],
                    claimed_event["source"],
                    claimed_event["status"],
                    "disabled",
                )
            continue

        claimed_event = claim_notification(operation_id)
        if not claimed_event:
            continue
        delivery = send_vm_reset_notification(claimed_event)
        delivery_result = f"{delivery['delivered']}/{delivery['attempted']}"
        update_pending_event(operation_id, delivery_result=delivery_result)
        logger.info(
            "Pending event operation_id=%s event_type=%s vm_id=%s vm_name=%s "
            "source=%s status=%s delivery_result=%s",
            operation_id,
            claimed_event["event_type"],
            claimed_event["vm_id"],
            claimed_event["vm_name"],
            claimed_event["source"],
            claimed_event["status"],
            delivery_result,
        )


def _write_cache():
    now = datetime.now(ZoneInfo("Asia/Jakarta"))
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    try:
        summary = get_host_summary()
        host_summary_available = True
        logger.info("VMware host summary collection succeeded")
    except Exception as exc:
        summary = unavailable_host_summary()
        host_summary_available = False
        logger.warning("VMware host summary collection unavailable: %s", exc)

    ilo_health = collect_optional_subsystem(
        "iLO health",
        get_ilo_health,
        unavailable_ilo_health
    )

    if not host_summary_available:
        collect_hardware_events(summary, ilo_health, timestamp)
        logger.warning("Dashboard cache write skipped because ESXi host is unavailable")
        return

    collect_datastore_events(summary, timestamp)

    try:
        hardware = get_hardware_summary()
        hardware_available = True
        logger.info("VMware hardware collection succeeded")
    except Exception as exc:
        hardware_available = False
        logger.warning("VMware hardware collection unavailable: %s", exc)

    collect_hardware_events(summary, ilo_health, timestamp)

    try:
        vm_list = get_vm_list()
        logger.info("VM inventory collection succeeded")
    except Exception as exc:
        logger.warning("VM inventory collection unavailable: %s", exc)
        return

    logger.info("VM inventory count=%s", len(vm_list))
    collect_vm_power_events(vm_list, timestamp)
    collect_snapshot_events()

    if not hardware_available:
        previous_cache = load_cache()
        previous_hardware = (
            previous_cache.get("hardware")
            if isinstance(previous_cache, dict)
            else None
        )
        if not isinstance(previous_hardware, dict):
            logger.warning(
                "Dashboard cache write skipped because no hardware fallback is available"
            )
            return
        hardware = dict(previous_hardware)

    hardware["ilo"] = ilo_health
    alerts = generate_alerts(hardware)

    data = {
        "updated": {
            "summary": timestamp,
            "vm": timestamp,
            "hardware": timestamp,
        },
        "summary": summary,
        "hardware": hardware,
        "vm": vm_list,
        "alerts": alerts,
    }

    try:
        save_cache(data)
        logger.info("Dashboard cache write succeeded")
    except Exception:
        logger.exception("Dashboard cache write failed")
        raise


def write_cache():
    try:
        _write_cache()
    finally:
        try:
            collect_pending_events()
        except Exception:
            logger.warning("Pending event queue processing failed")


while True:
    try:
        logger.info("Updating cache...")
        write_cache()
        logger.info("Done")
    except Exception:
        logger.exception("Collector error")

    time.sleep(30)
