#!/bin/bash

# exec: gunicorn must be PID 1 for SIGTERM to reach it (see app.sh).
# The hooks service runs the live call pipelines, so the graceful timeout
# must outlast a typical call — a deploy drains conversations, not drops them.
exec /app/.venv/bin/gunicorn src.main_hooks:app \
  --workers ${HOOKS_WORKERS_NUM:-2} \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind=0.0.0.0:${HOOKS_PORT:-8081} \
  --graceful-timeout ${HOOKS_GRACEFUL_TIMEOUT:-330} \
  --access-logfile - \
  --error-logfile - \
  --forwarded-allow-ips='*'
