# Two stages so the build toolchain (uv) never reaches the published image.
#
# The base tag and `requires-python` in pyproject.toml have to stay in step:
# UV_PYTHON_DOWNLOADS=never keeps uv on the image interpreter, and the venv
# copied into the runtime stage links to that same /usr/local/bin/python3.13.
#
# Size matters here: the hooks pods pull this image on cold nodes during every
# rollout. Silero VAD and Smart Turn v3 run on onnxruntime, so the torch-based
# pipecat extra (`local-smart-turn`, which drags in the CUDA stack) is NOT
# installed — keep it that way.

# ---------- build ----------------------------------------------------------
FROM python:3.13.12-slim AS build

ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Pipecat imports the sentence tokenizer at startup. Bundle its data so
# workers can start and tokenize speech without downloading from GitHub.
RUN .venv/bin/python -c "import nltk; nltk.download('punkt_tab', download_dir='/opt/nltk_data', raise_on_error=True)"

# ---------- runtime --------------------------------------------------------
FROM python:3.13.12-slim

# libgomp1: OpenMP runtime onnxruntime links against (VAD + turn analyzer).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV NLTK_DATA=/opt/nltk_data

COPY --from=build /app/.venv /app/.venv
COPY --from=build /opt/nltk_data /opt/nltk_data

COPY src ./src
COPY alembic.ini alembic_control.ini ./
COPY scripts ./scripts
RUN chmod +x -R /app/scripts

# Never run the platform as root: a compromised call pipeline or template
# renderer should not own the container.
RUN useradd --system --no-create-home --uid 10001 voxline
USER voxline

# app 8080, hooks 8081 (see scripts/)
EXPOSE 8080 8081

ENTRYPOINT []
CMD ["echo", "No command specified"]
