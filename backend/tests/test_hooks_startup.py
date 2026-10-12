"""Hooks readiness must wait for the engine and both bundled models."""

# Configure example credentials before importing the app; no services are used.
from tests import support  # noqa: F401  isort: skip

import builtins
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from uvicorn import Config
from uvicorn.lifespan.on import LifespanOn

from src import main_hooks
from src.application.worker import runner
from src.integrations.vad import onnx_sessions
from src.integrations.vad.silero import SILERO_MODEL_PATH, SMART_TURN_MODEL_PATH


@pytest.fixture
def infrastructure(monkeypatch):
    mocks = SimpleNamespace(
        startup=AsyncMock(), shutdown=AsyncMock(), drain=AsyncMock()
    )
    monkeypatch.setattr(main_hooks, "startup", mocks.startup)
    monkeypatch.setattr(main_hooks, "shutdown", mocks.shutdown)
    monkeypatch.setattr(runner, "drain", mocks.drain)
    monkeypatch.setattr(onnx_sessions, "_sessions", {})
    return mocks


async def test_uvicorn_startup_completes_only_after_both_models_load(
    infrastructure, monkeypatch
):
    lifespan = LifespanOn(Config(main_hooks.app, lifespan="on"))
    real_session = onnx_sessions.ort.InferenceSession
    loaded = []

    def load(*args, **kwargs):
        assert not lifespan.startup_event.is_set()
        session = real_session(*args, **kwargs)
        loaded.append(session)
        return session

    monkeypatch.setattr(onnx_sessions.ort, "InferenceSession", load)
    await lifespan.startup()
    try:
        assert not lifespan.should_exit
        assert not lifespan.startup_failed
        assert len(loaded) == 2
        assert list(onnx_sessions._sessions.values()) == loaded
        infrastructure.startup.assert_awaited_once_with(main_hooks.SETTINGS)
        infrastructure.shutdown.assert_not_awaited()
        infrastructure.drain.assert_not_awaited()
    finally:
        await lifespan.shutdown()
    infrastructure.drain.assert_awaited_once_with()
    infrastructure.shutdown.assert_awaited_once_with(main_hooks.SETTINGS)


@pytest.mark.parametrize("stage", ["runner", "silero", "smart_turn"])
async def test_warmup_failure_stops_uvicorn_startup(stage, infrastructure, monkeypatch):
    lifespan = LifespanOn(Config(main_hooks.app, lifespan="on"))
    if stage == "runner":
        real_import = builtins.__import__

        def import_module(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "src.application.worker" and "runner" in fromlist:
                raise ImportError("runner import failed")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", import_module)
    else:
        real_session = onnx_sessions.ort.InferenceSession
        failing_path = SILERO_MODEL_PATH if stage == "silero" else SMART_TURN_MODEL_PATH

        def load(path, **kwargs):
            if path == failing_path:
                raise RuntimeError("model load failed")
            return real_session(path, **kwargs)

        monkeypatch.setattr(onnx_sessions.ort, "InferenceSession", load)

    await lifespan.startup()
    assert lifespan.startup_failed
    assert lifespan.should_exit
    infrastructure.shutdown.assert_awaited_once_with(main_hooks.SETTINGS)
    infrastructure.drain.assert_not_awaited()
