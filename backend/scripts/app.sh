#!/bin/bash

# exec, and the venv binary directly: gunicorn must be PID 1 to receive
# docker's SIGTERM — a shell (or `uv run`, which does not exec) in between
# swallows it and every stop waits out the full grace period into a SIGKILL.
exec /app/.venv/bin/gunicorn src.main:app \
  --workers ${APP_WORKERS_NUM:-4} \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind=0.0.0.0:8080 \
  --access-logfile - \
  --error-logfile - \
  --forwarded-allow-ips='*'
