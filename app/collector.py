import time
from datetime import datetime
from zoneinfo import ZoneInfo

from services.cache import save_cache
from services.logger import logger
from services.vmware import get_vm_list, get_host_summary
from services.hardware import get_hardware_summary
from services.ilo import get_ilo_health


def write_cache():
    now = datetime.now(ZoneInfo("Asia/Jakarta"))

    summary = get_host_summary()
    hardware = get_hardware_summary()
    ilo_health = get_ilo_health()
    vm_list = get_vm_list()

    hardware["ilo"] = ilo_health

    # DEBUG
    logger.info(f"Hardware type: {type(hardware)}")
    logger.info(f"Hardware content: {hardware}")

    data = {
        "updated": {
            "summary": now.strftime("%Y-%m-%d %H:%M:%S"),
            "vm": now.strftime("%Y-%m-%d %H:%M:%S"),
            "hardware": now.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "summary": summary,
        "hardware": hardware,
        "vm": vm_list,
    }

    logger.info(f"Cache data: {data}")

    save_cache(data)


while True:
    try:
        logger.info("Updating cache...")
        write_cache()
        logger.info("Done")
    except Exception:
        logger.exception("Collector error")

    time.sleep(30)
