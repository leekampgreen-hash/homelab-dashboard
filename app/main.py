from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from services.cache import load_cache

app = FastAPI(title="HomeLab Dashboard")

templates = Jinja2Templates(directory="templates")


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


@app.get("/health")
async def health():

    return {
        "status": "healthy"
    }
