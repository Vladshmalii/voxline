"""Lazy CPU inference sessions shared by calls within one worker process.

Only sessions belong here: audio buffers, recurrent state and analyzers must
remain per call. Keep sessions alive for the worker's lifetime to avoid repeated
model loading and graph optimization between calls.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

import onnxruntime as ort

_sessions: dict[tuple[str, int], ort.InferenceSession] = {}
_session_lock = Lock()


def _reset_after_fork() -> None:
    """A child must neither reuse the parent's sessions nor inherit its lock."""
    global _sessions, _session_lock
    _sessions = {}
    _session_lock = Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


def cpu_session(model_path: str, *, cpu_count: int = 1) -> ort.InferenceSession:
    """Load once per model path/thread setting, including concurrent cold calls.

    The lock covers construction only. CPU sessions support concurrent run()
    calls with separate input/output arrays; inference needs no global lock.
    Failed loads are not cached and can be retried by a later call.
    """
    key = (str(Path(model_path).resolve()), cpu_count)
    with _session_lock:
        if key not in _sessions:
            options = ort.SessionOptions()
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = cpu_count
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _sessions[key] = ort.InferenceSession(
                key[0], sess_options=options, providers=["CPUExecutionProvider"]
            )
        return _sessions[key]
