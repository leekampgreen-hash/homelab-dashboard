from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates

from services.cache import load_cache
from services.docker import DockerMonitorUnavailableError, get_docker_status
from services.logger import logger
from services.pending_events import create_pending_event
from services.vmware import (
    create_snapshot,
    delete_snapshot,
    list_snapshots,
    list_virtual_machines,
    power_vm,
    restore_snapshot,
    get_task_status_by_id,
    power_on_vm,
    power_off_vm,
    reset_vm,
    shutdown_guest,
    suspend_vm,
)

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


@app.get("/api/docker")
async def api_docker():
    try:
        return {"success": True, "data": get_docker_status()}
    except DockerMonitorUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def vmware_error(message, operation, exc):
    logger.exception("%s failed", operation)
    return HTTPException(status_code=500, detail=message)


def accepted_task(task):
    return {
        "status": "accepted",
        "task_id": task["id"],
        "task_state": task["state"]
    }


def requester_from(request):
    return request.client.host if request.client else "unknown"


def reset_source_from(request):
    return "telegram" if request.headers.get("X-Homelab-Source") == "telegram" else "dashboard"


async def run_vm_action(request, vm_id, action, operation, *args):
    try:
        task = action(vm_id, *args, requester=requester_from(request))
        return accepted_task(task)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise vmware_error(f"Unable to {operation}", operation, exc)


@app.get("/api/vm")
async def api_vms():
    try:
        return {"success": True, "data": list_virtual_machines()}
    except Exception as exc:
        raise vmware_error("Unable to list virtual machines", "List virtual machines", exc)


@app.post("/api/vm/{vm_id}/poweron")
async def api_vm_power_on(vm_id: str, request: Request):
    return await run_vm_action(request, vm_id, power_on_vm, "power on VM")


@app.post("/api/vm/{vm_id}/poweroff")
async def api_vm_power_off(vm_id: str, request: Request):
    return await run_vm_action(request, vm_id, power_off_vm, "power off VM")


@app.post("/api/vm/{vm_id}/reset")
async def api_vm_reset(vm_id: str, request: Request):
    try:
        task = reset_vm(vm_id, requester=requester_from(request))
        event = create_pending_event("vm_reset", task, reset_source_from(request))
        logger.info(
            "Pending event operation_id=%s event_type=%s vm_id=%s vm_name=%s "
            "source=%s status=%s",
            event["operation_id"],
            event["event_type"],
            event["vm_id"],
            event["vm_name"],
            event["source"],
            event["status"],
        )
        return accepted_task(task)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise vmware_error("Unable to reset VM", "reset VM", exc)


@app.post("/api/vm/{vm_id}/shutdown")
async def api_vm_shutdown(vm_id: str, request: Request):
    return await run_vm_action(request, vm_id, shutdown_guest, "shut down guest")


@app.post("/api/vm/{vm_id}/suspend")
async def api_vm_suspend(vm_id: str, request: Request):
    return await run_vm_action(request, vm_id, suspend_vm, "suspend VM")


@app.get("/api/vm/{vm_id}/snapshots")
async def api_vm_snapshots(vm_id: str):
    try:
        return {"status": "success", "data": list_snapshots(vm_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise vmware_error("Unable to list snapshots", "List snapshots", exc)


@app.post("/api/vm/{vm_id}/snapshots")
async def api_create_snapshot(vm_id: str, request: Request):
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Snapshot name is required")

    try:
        task = create_snapshot(
            vm_id,
            name,
            payload.get("description", ""),
            payload.get("memory", False),
            payload.get("quiesce", False)
        )
        return {
            "status": "accepted",
            "task_id": task["id"],
            "task_state": task["state"]
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise vmware_error("Unable to create snapshot", "Create snapshot", exc)


@app.post("/api/vm/{vm_id}/snapshots/{snapshot_id}/restore")
async def api_restore_snapshot(vm_id: str, snapshot_id: str):
    try:
        task = restore_snapshot(vm_id, snapshot_id)
        return {"status": "accepted", "task_id": task["id"], "task_state": task["state"]}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise vmware_error("Unable to restore snapshot", "Restore snapshot", exc)


@app.delete("/api/vm/{vm_id}/snapshots/{snapshot_id}")
async def api_delete_snapshot(vm_id: str, snapshot_id: str):
    try:
        task = delete_snapshot(vm_id, snapshot_id)
        return {"status": "accepted", "task_id": task["id"], "task_state": task["state"]}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise vmware_error("Unable to delete snapshot", "Delete snapshot", exc)


@app.get("/api/tasks/{task_id}")
async def api_task_status(task_id: str):
    try:
        return {"success": True, "data": get_task_status_by_id(task_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise vmware_error("Unable to get task status", "Get task status", exc)


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
