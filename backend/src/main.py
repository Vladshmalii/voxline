import gc
from contextlib import asynccontextmanager

from fastapi import FastAPI, responses
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from src.settings import SETTINGS, logger  # isort: skip - runs Config.init first

from src.controller.api import router
from src.infrastructure import shutdown, startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up")
    await startup(SETTINGS)
    # The playground runs call pipelines in this process too, and each one
    # ends with a full collection (``force_gc`` in the engine's session).
    # Freezing the startup heap keeps that collection to the calls' objects.
    gc.collect()
    gc.freeze()
    yield
    logger.info("Shutting down")
    await shutdown(SETTINGS)


app = FastAPI(
    root_path="/api",
    debug=not SETTINGS.application_state.is_production,
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health", include_in_schema=False)
async def health():
    return responses.Response()


@app.get("/ready", include_in_schema=False)
async def ready():
    return responses.Response()


app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.origins.split(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # History exports name their file here; a cross-origin admin can't read
    # it unless it is exposed.
    expose_headers=["Content-Disposition"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SETTINGS.secret_key,
    https_only=SETTINGS.application_state.is_production,
)
