#!/bin/bash

# exec: taskiq must be PID 1 to receive SIGTERM (see app.sh).
# The dialing worker: small idempotent taskiq tasks (dial_call, sweeps).
# Scale instances freely — claims are guarded in SQL, sweeps are idempotent.
exec /app/.venv/bin/taskiq worker src.application.worker.tasks:broker \
  --workers ${WORKER_PROCESSES:-1} \
  --max-async-tasks ${WORKER_MAX_ASYNC_TASKS:-32}
