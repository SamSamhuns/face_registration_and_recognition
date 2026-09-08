"""
Main fastapi server file.

Run it with the standard ASGI entrypoint, from the directory that contains `app/`:

    uvicorn app.server:app --host 0.0.0.0 --port 8080          # prod
    uvicorn app.server:app --reload                            # dev

Do not run `python app/server.py`: that puts `app/` itself on sys.path instead of
its parent, so `import app` fails.
"""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import inference
from app.routes import person, recognize_person, register_person

logger = logging.getLogger("server")

# resolved from this file, not the process cwd, so the app runs from any directory
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    inference.init_connections()
    try:
        yield
    finally:
        inference.close_connections()


def get_application(title="Face Registration and Recognition"):
    """Gets FastAPI application object with CORS enabled."""
    fastapi_app = FastAPI(title=title, version="1.0.0", lifespan=lifespan)
    fastapi_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return fastapi_app


app = get_application()
app.include_router(person.router)
app.include_router(recognize_person.router)
app.include_router(register_person.router)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Adds an X-Process-Time header to the response indicating the api request processing time."""
    start_time = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = str(time.perf_counter() - start_time)
    return response


@app.get("/")
async def index():
    """Root endpoint. Returns a welcome message."""
    return {"Welcome to Person Face Registration & Recognition Service": "Please visit /docs for list of apis"}


@app.get("/health")
async def health_check():
    """Liveness probe. Says the process is up, not that its dependencies are."""
    return {"status": "healthy"}


@app.get("/favicon.ico")
async def favicon():
    """Favicon endpoint. Returns the favicon."""
    return FileResponse(path=STATIC_DIR / "favicon.ico")
