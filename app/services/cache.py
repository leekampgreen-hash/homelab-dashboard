import json
import os

CACHE_FILE = "cache/dashboard.json"


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}

    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(data):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)

    tmp = CACHE_FILE + ".tmp"

    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)

    os.replace(tmp, CACHE_FILE)
