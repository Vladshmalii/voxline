"""The hooks entry point: the surface telephony providers connect to.

Same shape as the payment and chatbot hooks services — a second FastAPI
process, deployed separately from the admin API (``src/main.py``) and the
dispatcher (``src/worker.py``). It carries the media WebSockets and status
webhooks, which means it also *runs the call pipelines*: whichever hooks
worker a provider's socket lands on claims the call from the registry and
runs it. Scale this service for call capacity; scale the admin API for
humans.

Exposure: the jambonz bridge reaches it over the VPC; Twilio (the SLA backup
carrier) over the public ingress with TLS. Per-telephony-row media URLs pick
which hostname a given trunk is told to use.
"""

import gc
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, responses

# Settings first: importing it runs the core Config.init, which everything
# below (ORM base, session maker) requires.
from src.settings import SETTINGS, logger  # isort: skip

from src.controller_hooks.api import router
from src.infrastructure import shutdown, startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up")
    await startup(SETTINGS)
    try:
        # Run after fork, in every hooks worker. Uvicorn starts serving only
        # after this lifespan yields; a failed warm-up must fail startup.
        started = perf_counter()
        logger.info("Hooks warm-up started: importing runner and loading local models")
        from src.application.worker import runner

        imported = perf_counter()
        from src.integrations.vad.silero import warmup_models

        warmup_models()
        warmed = perf_counter()
        # Everything loaded so far lives as long as the process. Freezing it
        # takes it out of the collector's scans, so the full collection each
        # call ends with (``force_gc`` in the engine's session) costs
        # milliseconds rather than a pause that clips other live calls' audio.
        gc.collect()
        gc.freeze()
        logger.info(
            f"Hooks warm-up complete: runner_import_ms={(imported - started) * 1000:.1f} "
            f"models_ms={(warmed - imported) * 1000:.1f} "
            f"total_ms={(warmed - started) * 1000:.1f} "
            f"frozen_objects={gc.get_freeze_count()}"
        )
        try:
            yield
        finally:
            logger.info("Shutting down: draining live calls")
            # A deploy must not cut conversations mid-sentence; pair this with a
            # graceful-timeout on the process manager longer than a typical call.
            await runner.drain()
    finally:
        await shutdown(SETTINGS)


app = FastAPI(
    root_path="/api",
    debug=not SETTINGS.application_state.is_production,
    lifespan=lifespan,
    openapi_url=None,
)
app.include_router(router)


@app.get("/health", include_in_schema=False)
async def health():
    return responses.Response()


@app.get("/ready", include_in_schema=False)
async def ready():
    # Uvicorn only serves this route once lifespan warm-up has succeeded.
    return responses.Response()
