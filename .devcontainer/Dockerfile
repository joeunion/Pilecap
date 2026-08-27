# The ROOM `scripts/setup.sh` runs in. It is not a second setup path and it
# must never become one: nothing here installs a Python dependency, creates a
# database, starts a container or writes a `.env`. Everything this image does
# is put the two tools `setup.sh` already assumes on a laptop — the pinned
# Python and the pinned `uv` — onto a machine that did not have them.
#
# Why a Dockerfile at all, when a features-only `devcontainer.json` is shorter:
# the `uv` line below. The repository already pins `uv` to an exact published
# image in the production `Dockerfile`, and a devcontainer that installed
# whatever the day's installer script or a third-party feature resolved would
# be a second, floating pin of the one tool that resolves every other version
# in the tree. One version of `uv`, named in two files, changed in both.

# THE SAME UPSTREAM IMAGE FAMILY AS THE PRODUCTION `Dockerfile`, one line up
# from its `-slim` — the full bookworm variant, because a development room
# needs the `git`, `curl` and build tools a deployment image is right to omit.
# The 3.12 series is `.python-version`, `requires-python` and that Dockerfile's
# pin; Django 5.2 LTS is what this template supports and a silent move to 3.13
# is a debugging session nobody asked for.
#
# NOT `mcr.microsoft.com/devcontainers/python:1-3.12-bookworm`, and the reason
# is measured rather than aesthetic. That image ships a yarn apt source whose
# signing key its keyring no longer carries, so `apt-get update` inside it ends
# in `E: The repository 'https://dl.yarnpkg.com/debian stable InRelease' is not
# signed.` and exits 100 — which kills EVERY feature that installs a package.
# On 2026-08-23 the docker-in-docker feature below failed exactly there.
# Deleting somebody else's broken apt source in a `RUN` line would be a
# workaround this repository would then own forever; the plain Python image has
# no yarn source, no Node, and is the one the tree already pins elsewhere.
# `common-utils` in `devcontainer.json` supplies the `vscode` user that the
# Microsoft image was the only reason to want.
FROM python:3.12-bookworm

# uv 0.12.5 — the exact version the production `Dockerfile` copies, from the
# same digest-addressable published image rather than a `curl | sh`. `uv` does
# not build the venv here: `setup.sh` runs `uv sync` at create time, against the
# workspace, where the lock file is.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /usr/local/bin/
