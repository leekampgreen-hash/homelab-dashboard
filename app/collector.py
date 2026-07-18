import time
from datetime import datetime

from services.cache import save_cache
from services.logger import logger
from services.vmware import get_vm_list, get_host_summary


def write_cache():
    data = {
        "updated": {
            "summary": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "vm": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hardware": None
        },
        "summary": get_host_summary(),
        "hardware": {},
        "vm": get_vm_list()
    }

    save_cache(data)


while True:
    try:
        logger.info("Updating cache...")
        write_cache()
        logger.info("Done")
    except Exception:
        logger.exception("Collector error")

    time.sleep(30)
