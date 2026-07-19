from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates

from services.cache import load_cache
from services.vmware import power_vm

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


@app.post("/api/vm/{vm_id}/power")
async def api_vm_power(vm_id: str, request: Request):
    payload = await request.json()
    action = payload.get("action")

    try:
        task_key = power_vm(vm_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="VM power action failed") from exc

    return {
        "status": "accepted",
        "task": task_key
    }


@app.get("/health")
async def health():

    return {
        "status": "healthy"
    }
