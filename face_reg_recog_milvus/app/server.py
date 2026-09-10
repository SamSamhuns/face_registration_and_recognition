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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import API_V1_PREFIX, CORS_ALLOW_CREDENTIALS, CORS_ALLOW_ORIGINS
from app.deps import close_clients, create_clients
from app.errors import AppError, status_for
from app.routes import health, persons, recognitions
from app.schemas import ErrorDetail

logger = logging.getLogger("server")

# resolved from this file, not the process cwd, so the app runs from any directory
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Open every client once at startup and close them at shutdown.

    Anything created here is reachable from a request via app.state, which is what
    lets routes use Depends instead of reaching for module globals.
    """
    app.state.clients = await create_clients()
    try:
        yield
    finally:
        await close_clients(app.state.clients)


def get_application(title: str = "Face Registration and Recognition") -> FastAPI:
    """Build the FastAPI app: middleware, routers and error handling."""
    fastapi_app = FastAPI(
        title=title,
        version="2.0.0",
        lifespan=lifespan,
        description="Register faces and identify them against the registered population.",
    )
    fastapi_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGINS,
        # Never both "*" and credentials: browsers reject that pairing outright.
        allow_credentials=CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    fastapi_app.include_router(health.router)
    fastapi_app.include_router(persons.router, prefix=API_V1_PREFIX)
    fastapi_app.include_router(recognitions.router, prefix=API_V1_PREFIX)

    @fastapi_app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        """
        One place decides how a domain error becomes a response.

        Previously each route caught bare Exception and raised HTTPException(400),
        so a missing person, an unreadable image and a dead database were
        indistinguishable to the caller.
        """
        code = status_for(exc)
        if code >= 500:
            logger.exception("unhandled domain error: %s", exc.message)
        else:
            logger.info("%s -> %s: %s", type(exc).__name__, code, exc.message)
        body = ErrorDetail(error=type(exc).__name__, detail=exc.message)
        return JSONResponse(status_code=code, content=body.model_dump())

    return fastapi_app


app = get_application()


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Adds an X-Process-Time header to the response indicating the api request processing time."""
    start_time = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = str(time.perf_counter() - start_time)
    return response


@app.get("/", include_in_schema=False)
async def index():
    """Root endpoint. Points at the docs."""
    return {
        "service": "Person Face Registration & Recognition",
        "docs": "/docs",
        "api": API_V1_PREFIX,
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Favicon endpoint. Returns the favicon."""
    return FileResponse(path=STATIC_DIR / "favicon.ico")
