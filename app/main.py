from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from services.cache import load_cache

app = FastAPI(title="HomeLab Dashboard")

templates = Jinja2Templates(directory="templates")


def is_data_current(updated):

    timestamp = updated.get("summary")

    if not timestamp:
        return False

    try:
        last_updated = datetime.strptime(
            timestamp,
            "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=ZoneInfo("Asia/Jakarta"))

        age = datetime.now(ZoneInfo("Asia/Jakarta")) - last_updated

        return age.total_seconds() <= 90
    except ValueError:
        return False


@app.get("/")
async def home(request: Request):

    data = load_cache()
    updated = data.get("updated", {})

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "summary": data.get("summary", {}),
            "vm": data.get("vm", []),
            "updated": updated,
            "data_current": is_data_current(updated),
            "hardware": data.get("hardware", {})
        }
    )


@app.get("/api/dashboard")
async def api_dashboard():

    return load_cache()


@app.get("/health")
async def health():

    return {
        "status": "healthy"
    }
