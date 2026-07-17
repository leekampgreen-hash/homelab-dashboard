import json
import os

CACHE_FILE="cache/dashboard.json"

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE,"r") as f:
        return json.load(f)

def save_cache(data):
    tmp=CACHE_FILE+".tmp"
    with open(tmp,"w") as f:
        json.dump(data,f,indent=4)
    os.replace(tmp,CACHE_FILE)
