"""Smart Safety Monitoring — FastAPI backend.

Chạy: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
import mqtt_service
from database import init_db
from routes import router
from ws import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    client = mqtt_service.start(asyncio.get_running_loop())
    yield
    if client is not None:
        client.loop_stop()
        client.disconnect()


app = FastAPI(title="Smart Safety Monitoring", version="1.0", lifespan=lifespan)
app.include_router(router)
app.mount("/snapshots", StaticFiles(directory=config.SNAPSHOT_DIR), name="snapshots")


@app.get("/")
def index():
    dash = config.DASHBOARD_DIR / "index.html"
    return FileResponse(dash) if dash.exists() else {"service": "safety-backend", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok", "mqtt_clients": len(hub.clients)}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # giữ kết nối; dashboard có thể gửi ping
    except WebSocketDisconnect:
        hub.disconnect(ws)
