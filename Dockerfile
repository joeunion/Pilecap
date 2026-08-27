# The two processes this product runs, from one build.
#
#   docker build --target web    -t djb-web    .
#   docker build --target worker -t djb-worker .
#
# They are two targets rather than two Dockerfiles because they are the same
# tree, the same dependencies and the same settings — only the command differs.
# A second Dockerfile would drift from the first the first time somebody added
# a dependency, and the drift would show up as a worker that cannot import the
# service the web process just started calling.
#
# Layers are ordered so the expensive one is the one that changes least: the
# lock file resolves and installs before any application code is copied, so a
# one-line change to a service re-runs the copy and nothing else.
#
# Compose runs Postgres, Redis and Temporal for a laptop; the app and the worker
# run on the host there. These images are what a deployment runs.

# --- The runtime floor, shared by every stage --------------------------------
# Pinned to the 3.12 series because `requires-python = ">=3.12"` and Django 5.2
# LTS is what this template supports; a silent move to 3.13 is a debugging
# session nobody asked for.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app


# --- Build: resolve, install, collect static ---------------------------------

FROM base AS build

# uv comes from its own published image rather than a curl|sh, so the version
# is a pinned digest-addressable artifact like every other dependency here.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# The dependency layer. `--frozen` refuses to re-resolve: the image gets exactly
# what `uv.lock` says and exactly what the gate measured, or the build fails.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Static files are baked in, not collected at boot: a container that runs
# `collectstatic` on start is a container whose first request is slow, whose
# filesystem has to be writable, and which fails differently on every replica.
#
# The build-time environment below exists only for the duration of this one
# command. `config.settings.production` refuses to start on the published
# development SECRET_KEY, so a throwaway is generated here; nothing about it is
# written into the image, and nothing at runtime reads it.
#
# THE LINE HAS TO SATISFY EVERY REFUSAL `production` HAS, and it did not: this
# build was broken on main until somebody first tried to run it, because
# nothing in the tree ever built the image. `collectstatic` imports settings
# like any other management command, so every guard between here and the
# static finders fires:
#
#   * `DATABASE_NAME is not set and there is no default`. `.dockerignore`
#     excludes `.env`, deliberately, so there is nothing to fall back to and
#     nothing here supplied one. The build died at settings import.
#   * production also refuses `DATABASE_PASSWORD` absent OR equal to the
#     published `djb`, so supplying only a name would have died one line later.
#
# Both are answered the way the two keys above are: a throwaway, generated in
# the shell, alive for one command. `build.invalid` is a name nothing can
# resolve — and nothing tries, because `collectstatic` opens no connection.
# The fix belongs here rather than in a guard, because the guards are right:
# a deployment that reached this point with no database configured would be a
# deployment about to fail its first request.
RUN SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
    CONNECTIONS_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
    DATABASE_NAME=build.invalid \
    DATABASE_HOST=build.invalid \
    DATABASE_PASSWORD="$(python -c 'import secrets; print(secrets.token_hex(16))')" \
    ALLOWED_HOSTS=build.invalid \
    DEBUG=0 \
    python manage.py collectstatic --noinput --clear


# --- Runtime: the tree, owned by nobody who can change it --------------------

FROM base AS runtime

# psycopg is installed as `psycopg[binary]`, so there is no libpq to add here;
# `curl` is for a container healthcheck a deployment may point at /healthz.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd --gid 10001 djb; \
    useradd --uid 10001 --gid djb --no-create-home --home-dir /app djb

# Copied as root and owned by root: the process user can read the application
# and cannot rewrite it. A container that can edit its own code is a container
# where a file-write vulnerability becomes remote code execution that survives
# a restart.
COPY --from=build /app /app

USER djb:djb

EXPOSE 8000


# --- web ---------------------------------------------------------------------
# ASGI, because sockets and the MCP mount are not WSGI-shaped. One worker per
# container: replicas are the deployment's business, and a process manager
# inside a container hides a crash from whatever is meant to restart it.

FROM runtime AS web

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]


# --- worker ------------------------------------------------------------------
# The Temporal worker: the same tree, polling the task queue. It serves no HTTP
# and is not `/healthz`-checked — Temporal's own worker visibility is what says
# whether it is polling.

FROM runtime AS worker

CMD ["python", "-m", "apps.workflows.worker"]
