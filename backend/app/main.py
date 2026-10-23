"""FastAPI-бекенд панели Trofeo Vision 11.3.

Запуск (строго один воркер: процесс владеет USB-устройством):
    uvicorn app.main:app --host 0.0.0.0 --port 8888

Dev-режим без панели:
    PANEL_NO_USB=1 uvicorn app.main:app --port 8888 --reload
"""
import io
import os
import re
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import metrics
from .config import AppConfig, ConfigStore, IMAGES_DIR
from .render import render_frame, disk_paths
from .sender import Sender
from .widgets import CATALOG

store = ConfigStore()
sender: Sender | None = None

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sender
    usb_enabled = os.environ.get("PANEL_NO_USB", "") != "1"
    sender = Sender(store, usb_enabled=usb_enabled)
    sender.start()
    yield
    sender.stop()
    sender.join(timeout=5)


app = FastAPI(title="Trofeo Vision 11.3 panel", lifespan=lifespan)

# CORS для dev-фронтенда (React на другом порту)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _render_png(cfg: AppConfig) -> bytes:
    img = render_frame(cfg, metrics.snapshot(disk_paths(cfg)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Статус и конфиг ───────────────────────────────────────────────
@app.get("/api/status")
def get_status():
    st = sender.status()
    st["remote_metrics"] = metrics.remote_info()
    return st


@app.post("/api/metrics")
def post_metrics(payload: dict):
    """Метрики удалённой машины (Mac): показываются на панели, пока
    приходят чаще TTL; затем демон возвращается к метрикам хоста."""
    metrics.set_remote(payload)
    return {"ok": True, "ttl_sec": metrics.REMOTE_TTL_SEC}


@app.get("/api/config")
def get_config() -> AppConfig:
    return store.get()


@app.put("/api/config")
def put_config(cfg: AppConfig) -> AppConfig:
    # Валидация уже прошла в pydantic; сохраняем и применяем со след. кадра
    return store.set(cfg)


@app.get("/api/widgets")
def get_widgets():
    return CATALOG


# ── Предпросмотр ──────────────────────────────────────────────────
@app.get("/api/preview.png")
def preview_current():
    """PNG-кадр по текущему сохранённому конфигу."""
    return Response(_render_png(store.get()), media_type="image/png")


@app.post("/api/preview.png")
def preview_draft(cfg: AppConfig):
    """PNG-кадр по черновику конфига из тела запроса, без сохранения."""
    return Response(_render_png(cfg), media_type="image/png")


# ── Картинки для виджета image ────────────────────────────────────
@app.get("/api/images")
def list_images():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.name for p in IMAGES_DIR.iterdir() if p.is_file())


@app.post("/api/images")
async def upload_image(file: UploadFile):
    name = re.sub(r"[^\w.\-]", "_", os.path.basename(file.filename or ""))
    ext = os.path.splitext(name)[1].lower()
    if not name or ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(400, f"allowed formats: {sorted(ALLOWED_IMAGE_EXT)}")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "file exceeds 20 MB")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (IMAGES_DIR / name).write_bytes(data)
    return {"name": name, "size": len(data)}


@app.delete("/api/images/{name}")
def delete_image(name: str):
    path = (IMAGES_DIR / os.path.basename(name)).resolve()
    if IMAGES_DIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "no such file")
    path.unlink()
    return {"deleted": name}


# ── Собранный фронтенд (frontend/dist), если есть ─────────────────
# В dev фронт ходит через vite с прокси, в проде раздаётся отсюда,
# и весь сервис работает одним процессом.
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
