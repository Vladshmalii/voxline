"""Import each process entry point without a pre-initialized shared Config."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("module", "attributes"),
    [
        ("src.main", ("app",)),
        ("src.main_hooks", ("app",)),
        ("src.application.worker.tasks", ("broker", "scheduler")),
        ("src.application.worker.runner", ("drain",)),
        ("src.sync_db", ("run_migrations",)),
    ],
)
def test_entrypoint_imports_in_fresh_process(module, attributes):
    # Example credentials only; importing must not connect to external services.
    env = {
        **os.environ,
        **{
            key: value
            for key, value in dotenv_values(ROOT / ".env.example").items()
            if value is not None
        },
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                f"import importlib; module = importlib.import_module({module!r}); "
                f"[getattr(module, name) for name in {attributes!r}]"
            ),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
