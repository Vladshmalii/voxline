#!/bin/bash

# exec: taskiq must be PID 1 to receive SIGTERM (see app.sh).
# The cron side of the worker: fires sweep_calls once a minute. One instance
# is enough; extras are safe (sweeps are idempotent) but pointless.
exec /app/.venv/bin/taskiq scheduler src.application.worker.tasks:scheduler
