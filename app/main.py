from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

import json

app = FastAPI(title="HomeLab Dashboard")

templates = Jinja2Templates(directory="templates")

CACHE_FILE = "cache/dashboard.json"


def load_cache():

    with open(CACHE_FILE, "r") as f:
        return json.load(f)


@app.get("/")
async def home(request: Request):

    data = load_cache()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "summary": data.get("summary", {}),
            "vm": data.get("vm", []),
            "updated": data.get("updated", {}),
            "hardware": data.get("hardware", {})
        }
    )


@app.get("/api/dashboard")
async def api_dashboard():

    return load_cache()
