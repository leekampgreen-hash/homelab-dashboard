import json
import time
from datetime import datetime

from services.vmware import get_vm_list, get_host_summary

CACHE_FILE = "cache/dashboard.json"


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

    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=4)


while True:
    try:
        print("Updating cache...", flush=True)
        write_cache()
        print("Done", flush=True)
    except Exception as e:
        print(f"Collector error: {e}", flush=True)

    time.sleep(30)
