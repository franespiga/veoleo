"""Local web server. Programme rules stay in src/; the browser is the screen."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.database_manager import DatabaseManager
from src.web_api import router

WEB = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    DatabaseManager().ensure_ready()
    yield


app = FastAPI(title="Lectura", lifespan=lifespan)
app.include_router(router, prefix="/api")
app.mount("/static", StaticFiles(directory=WEB), name="static")


def _page() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/")
def landing() -> FileResponse:
    return _page()


@app.get("/leer")
def reading() -> FileResponse:
    return _page()


@app.get("/escribir")
def writing() -> FileResponse:
    return _page()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
