import time
from datetime import datetime
from zoneinfo import ZoneInfo

from services.cache import save_cache
from services.logger import logger
from services.vmware import get_vm_list, get_host_summary
from services.hardware import get_hardware_summary
from services.ilo import get_ilo_health
from services.alert_engine import generate_alerts


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


def collect_optional_subsystem(name, collector, fallback):
    try:
        result = collector()
        logger.info("%s collection succeeded", name)
        return result
    except Exception as exc:
        logger.warning("%s collection unavailable: %s", name, exc)
        return fallback()


def write_cache():
    now = datetime.now(ZoneInfo("Asia/Jakarta"))

    summary = collect_subsystem("VMware host summary", get_host_summary)
    hardware = collect_subsystem("VMware hardware", get_hardware_summary)
    ilo_health = collect_optional_subsystem(
        "iLO health",
        get_ilo_health,
        unavailable_ilo_health
    )
    vm_list = collect_subsystem("VM inventory", get_vm_list)
    logger.info("VM inventory count=%s", len(vm_list))

    hardware["ilo"] = ilo_health
    alerts = generate_alerts(hardware)

    data = {
        "updated": {
            "summary": now.strftime("%Y-%m-%d %H:%M:%S"),
            "vm": now.strftime("%Y-%m-%d %H:%M:%S"),
            "hardware": now.strftime("%Y-%m-%d %H:%M:%S"),
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


while True:
    try:
        logger.info("Updating cache...")
        write_cache()
        logger.info("Done")
    except Exception:
        logger.exception("Collector error")

    time.sleep(30)
