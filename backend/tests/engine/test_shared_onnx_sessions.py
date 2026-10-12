"""Real bundled models: session reuse must not mix call state or predictions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import numpy as np
import pytest
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer

from src.application.engine.config import TurnParams, VadConfig
from src.integrations.vad import build_turn_analyzer, build_vad, onnx_sessions
from src.integrations.vad.silero import SileroVAD, SmartTurnV3, warmup_models


@pytest.fixture
def analyzers(monkeypatch):
    monkeypatch.setattr(onnx_sessions, "_sessions", {})
    created = []

    def track(analyzer):
        created.append(analyzer)
        return analyzer

    yield track
    # Pipecat's analyzer cleanup does not wait for the thread, and Smart Turn
    # starts its executor only on first inference. Shut down any test executor
    # and wait, so running inference cannot outlive a test's patched cache.
    for analyzer in created:
        if analyzer._executor is not None:
            analyzer._executor.shutdown(wait=True, cancel_futures=True)


def test_concurrent_cold_calls_load_only_two_sessions(monkeypatch, analyzers):
    real_session = onnx_sessions.ort.InferenceSession
    loads = []
    barrier = Barrier(8)

    def counted_session(*args, **kwargs):
        loads.append((args, kwargs))
        return real_session(*args, **kwargs)

    monkeypatch.setattr(onnx_sessions.ort, "InferenceSession", counted_session)

    def start_call(i):
        barrier.wait(timeout=10)
        rate = 8000 if i % 2 else 16000
        vad = analyzers(build_vad(VadConfig(confidence=0.5 + i / 100), rate))
        turn = analyzers(build_turn_analyzer(TurnParams(max_delay_ms=1000 + i), rate))
        return vad, turn

    with ThreadPoolExecutor(max_workers=8) as executor:
        calls = list(executor.map(start_call, range(8)))

    assert len(loads) == 2
    assert len({id(vad._model.session) for vad, _ in calls}) == 1
    assert len({id(turn._session) for _, turn in calls}) == 1
    assert len({id(vad._model._state) for vad, _ in calls}) == 8
    assert len({id(turn._audio_buffer) for _, turn in calls}) == 8
    # Smart Turn builds its executor on first inference, so ask for it.
    executors = [vad._executor for vad, _ in calls]
    executors += [turn._model_executor for _, turn in calls]
    assert len({id(executor) for executor in executors}) == 16
    for i, (vad, turn) in enumerate(calls):
        assert vad.params.confidence == 0.5 + i / 100
        assert turn.params.stop_secs == (1000 + i) / 1000 + 2
        assert vad._model.session.get_providers() == ["CPUExecutionProvider"]
        assert turn._session.get_providers() == ["CPUExecutionProvider"]


def test_startup_warmup_is_reused_by_calls(monkeypatch, analyzers):
    warmup_models()
    warmed = list(onnx_sessions._sessions.values())
    assert len(warmed) == 2

    def must_not_reload(*args, **kwargs):
        raise AssertionError("a warmed model was loaded again")

    monkeypatch.setattr(onnx_sessions.ort, "InferenceSession", must_not_reload)
    warmup_models()
    calls = [
        (
            analyzers(build_vad(VadConfig(), rate)),
            analyzers(build_turn_analyzer(TurnParams(), rate)),
        )
        for rate in (8000, 16000)
    ]
    for vad, turn in calls:
        assert vad._model.session in warmed
        assert turn._session in warmed
        assert not vad._model._state.any()
        assert turn._audio_buffer == []
    assert calls[0][0]._model._state is not calls[1][0]._model._state
    assert calls[0][1]._audio_buffer is not calls[1][1]._audio_buffer


def test_cache_separates_models_and_thread_settings_and_retries(monkeypatch, tmp_path):
    monkeypatch.setattr(onnx_sessions, "_sessions", {})
    attempts = []

    def load(path, **kwargs):
        attempts.append((path, kwargs))
        if len(attempts) == 1:
            raise RuntimeError("load failed")
        return object()

    monkeypatch.setattr(onnx_sessions.ort, "InferenceSession", load)
    path = str(tmp_path / "model.onnx")
    with pytest.raises(RuntimeError, match="load failed"):
        onnx_sessions.cpu_session(path)
    first = onnx_sessions.cpu_session(path)
    assert onnx_sessions.cpu_session(str(tmp_path / "subdir/../model.onnx")) is first
    assert onnx_sessions.cpu_session(path, cpu_count=2) is not first
    assert onnx_sessions.cpu_session(str(tmp_path / "other.onnx")) is not first
    assert len(attempts) == 4


def test_fork_reset_discards_sessions_and_locked_parent_lock(monkeypatch):
    parent_lock = Lock()
    monkeypatch.setattr(onnx_sessions, "_sessions", {("model", 1): object()})
    monkeypatch.setattr(onnx_sessions, "_session_lock", parent_lock)
    with parent_lock:
        onnx_sessions._reset_after_fork()
        assert onnx_sessions._sessions == {}
        assert onnx_sessions._session_lock.acquire(blocking=False)
        onnx_sessions._session_lock.release()


@pytest.mark.parametrize("rates", [(8000, 16000), (16000, 16000)])
async def test_parallel_vad_matches_upstream_with_independent_resets(rates, analyzers):
    shared = [analyzers(SileroVAD(sample_rate=rate)) for rate in rates]
    reference = [analyzers(SileroVADAnalyzer(sample_rate=rate)) for rate in rates]
    for rate, current, original in zip(rates, shared, reference):
        current.set_sample_rate(rate)
        original.set_sample_rate(rate)
        # Exercise deliberate resets below, without the wall-clock reset.
        current._last_reset_time = original._last_reset_time = float("inf")
        assert current.__dict__.keys() == original.__dict__.keys()
        assert current._model.__dict__.keys() == original._model.__dict__.keys()

    rng = np.random.default_rng(42)
    for frame in range(30):
        if frame == 10:
            shared[0]._model.reset_states()
            reference[0]._model.reset_states()
        audio = [
            rng.integers(-4000, 4000, size=rate // 50, dtype=np.int16).tobytes()
            for rate in rates
        ]
        actual = await asyncio.gather(
            *(vad.analyze_audio(pcm) for vad, pcm in zip(shared, audio))
        )
        expected = [await vad.analyze_audio(pcm) for vad, pcm in zip(reference, audio)]
        assert actual == expected
        for current, original in zip(shared, reference):
            np.testing.assert_allclose(current._model._state, original._model._state)
            np.testing.assert_array_equal(
                current._model._context, original._model._context
            )
            assert current._vad_buffer == original._vad_buffer


@pytest.mark.parametrize("rates", [(8000, 16000), (16000, 16000)])
async def test_parallel_smart_turn_matches_upstream_and_survives_call_cleanup(
    rates, analyzers, monkeypatch
):
    shared = [analyzers(SmartTurnV3(sample_rate=rate)) for rate in rates]
    reference = [
        analyzers(LocalSmartTurnAnalyzerV3(sample_rate=rate)) for rate in rates
    ]
    rng = np.random.default_rng(7)
    for rate, current, original in zip(rates, shared, reference):
        current.set_sample_rate(rate)
        original.set_sample_rate(rate)
        assert current.__dict__.keys() == original.__dict__.keys()
        pcm = rng.integers(-4000, 4000, size=rate, dtype=np.int16).tobytes()
        current.append_audio(pcm, is_speech=True)
        original.append_audio(pcm, is_speech=True)

    expected = [await turn.analyze_end_of_turn() for turn in reference]
    actual = await asyncio.gather(*(turn.analyze_end_of_turn() for turn in shared))
    for (state, metrics), (expected_state, expected_metrics) in zip(actual, expected):
        assert state == expected_state
        assert metrics.probability == pytest.approx(
            expected_metrics.probability, abs=1e-7
        )

    # End one call while the other has work submitted to its own executor.
    shared[1].append_audio(np.zeros(rates[1], dtype=np.int16).tobytes(), is_speech=True)
    entered = Event()
    release = Event()
    predict = shared[1]._predict_endpoint

    def blocked_prediction(audio):
        entered.set()
        assert release.wait(timeout=10)
        return predict(audio)

    monkeypatch.setattr(shared[1], "_predict_endpoint", blocked_prediction)
    pending = asyncio.create_task(shared[1].analyze_end_of_turn())
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        shared[0].clear()
        ended = shared[0]._executor
        await shared[0].cleanup()
        # Upstream cleanup shuts the call's thread down (pipecat#5350) and
        # drops the executor, so a reused analyzer starts a fresh one.
        assert shared[0]._executor is None
        ended.shutdown(wait=True)
    finally:
        release.set()
    _, metrics = await pending
    assert metrics is not None
    replacement = analyzers(SmartTurnV3(sample_rate=16000))
    assert replacement._session is shared[1]._session
    assert replacement._audio_buffer == []
    assert not replacement.speech_triggered


@pytest.mark.parametrize("rate", [8000, 16000])
def test_vad_measures_volume_from_the_first_frame(rate, analyzers):
    # Upstream reads volume 0 until 400 ms of audio have arrived, and
    # min_volume gates speech on it: an "Алло?" at pickup went unheard.
    frame = np.full(rate // 50, 8000, dtype=np.int16).tobytes()
    ours = analyzers(SileroVAD(sample_rate=rate))
    upstream = analyzers(SileroVADAnalyzer(sample_rate=rate))
    for vad in (ours, upstream):
        vad.set_sample_rate(rate)

    assert upstream._get_smoothed_volume(frame) == 0
    assert ours._get_smoothed_volume(frame) > 0


@pytest.mark.parametrize("cls", [SileroVAD, SmartTurnV3])
async def test_cleanup_ends_the_call_thread(cls, analyzers):
    # A hooks process on 1.7.0 gained two threads per call until a full
    # collection happened to free the call's graph; 1.8 ends them in cleanup.
    analyzer = analyzers(cls(sample_rate=16000))
    analyzer.set_sample_rate(16000)
    pcm = np.zeros(16000 // 10, dtype=np.int16).tobytes()
    if cls is SileroVAD:
        await analyzer.analyze_audio(pcm)
    else:
        analyzer.append_audio(pcm, is_speech=True)
        await analyzer.analyze_end_of_turn()
    (thread,) = analyzer._executor._threads

    await analyzer.cleanup()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_disabled_smart_turn_does_not_load_session(analyzers):
    assert build_turn_analyzer(TurnParams(smart_turn=False), 16000) is None
    assert not onnx_sessions._sessions
