from fastapi import FastAPI, HTTPException

from services.docker_socket import DockerUnavailableError, read_container_status


app = FastAPI(title="Docker Monitor")


@app.get("/status")
async def status():
    try:
        return {"success": True, "data": read_container_status()}
    except DockerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
