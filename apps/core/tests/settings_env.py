# census: cross-app population=config/settings/*.py parses base.py for env reads
"""Settings-module helpers importable with no app registry: quality/tests collects them too."""

from __future__ import annotations

import ast
import importlib
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import environ

#: The checkout root from this file's place, never Django's settings (no registry here).
BASE_DIR = Path(__file__).resolve().parents[3]


@contextmanager
def _settings_module(name: str, **environment: str | None) -> Iterator[Any]:
    """Import a settings module under a given environment, then put it back.

    Settings are read at import time — the honest thing for settings to do, and
    awkward to test: the only way to see what a deployment with an S3 bucket
    gets is to import the module with the bucket set. So the module is reloaded,
    asserted on, and reloaded again with the original environment.
    `django.conf.settings` is a separate object and is untouched throughout.

    **A value of `None` CLEARS the key instead of setting it**, and that is the
    half a pinned environment cannot do without. A dict that only ever adds
    variables pins nothing about the ones it is silent on: the checkout's own
    `.env` supplies those, so the same assertion is green on a laptop with no
    sign-in door and red on one that has configured a client id — a test whose
    verdict is the machine it ran on. Clearing takes
    BOTH sources, because there are two: the process environment, and the `.env`
    file `config.settings.base` reads at import — `environ.Env.read_env`
    SETDEFAULTS, so a key popped here would be handed straight back by the
    reload. So `read_env` is wrapped for the length of the block and the cleared
    keys are popped again after it runs.
    """
    base = importlib.import_module("config.settings.base")
    is_base = name == base.__name__
    applied = {key: value for key, value in environment.items() if value is not None}
    cleared = tuple(key for key, value in environment.items() if value is None)
    read_env = environ.Env.read_env

    def _read_env_minus_the_cleared(_self: Any, *args: Any, **kwargs: Any) -> None:
        read_env(*args, **kwargs)
        for key in cleared:
            os.environ.pop(key, None)

    try:
        with mock.patch.dict(os.environ, applied):
            for key in cleared:
                os.environ.pop(key, None)
            with mock.patch.object(environ.Env, "read_env", _read_env_minus_the_cleared):
                importlib.reload(base)
                if is_base:
                    yield base
                else:
                    # Dropped rather than reloaded, both here and on the way
                    # out: `config.settings.production` raises unless the
                    # environment it demands is present, so it must be
                    # *executed* under the patch and simply not left behind
                    # afterwards.
                    sys.modules.pop(name, None)
                    yield importlib.import_module(name)
    finally:
        if not is_base:
            sys.modules.pop(name, None)
        importlib.reload(base)


# Every environment key `config/settings/base.py` reads under the identity, the
# front-end and the brand names — the population `PRODUCTION_ENVIRONMENT` has to
# be complete over, DERIVED from `base.py` below rather than typed here, because
# a hand list goes stale the day somebody adds the next key and nothing says so.
IDENTITY_KEY_PREFIXES = (
    "ZITADEL_",
    "GOOGLE_",
    "PRODUCT_BASE_URL",
    "PUBLIC_BASE_URL",
    "BRAND_ACCENT",
    # Both spellings, and the second one is the setting. I0 wrote `SIGN_IN_DOOR`
    # here one rung before the door existed; A5 reads the environment under the
    # product's own `DJB_` prefix (`DJB_SIGN_IN_DOOR`), which starts with none of
    # the names above — so the census could not see the key the rider was about
    # and the pin below would have been silent on exactly the setting that
    # decides where every person in the deployment types their password. The
    # bare name stays: a product that reads `SIGN_IN_DOOR` unprefixed is still
    # in the population this census is over.
    "SIGN_IN_DOOR",
    "DJB_SIGN_IN_DOOR",
)


def _base_settings_tree() -> ast.Module:
    """`config/settings/base.py` parsed: one named file, read directly (no tree walk, no seam)."""
    return ast.parse((BASE_DIR / "config" / "settings" / "base.py").read_text(encoding="utf-8"))


def identity_keys_base_reads() -> frozenset[str]:
    """Every `env.<kind>("<KEY>", …)` in `base.py` whose key is an identity one.

    Parsed rather than grepped: an `env.str(` split over two lines is invisible
    to a line-oriented census, and that is exactly the key the next F14 will be
    about.
    """
    found: set[str] = set()
    for node in ast.walk(_base_settings_tree()):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not isinstance(callee, ast.Attribute):
            continue
        receiver = callee.value
        if not isinstance(receiver, ast.Name) or receiver.id != "env":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if first.value.startswith(IDENTITY_KEY_PREFIXES):
                found.add(first.value)
    return frozenset(found)


# What `config.settings.production` refuses to start without, and what it
# refuses to read from the machine underneath it. A throwaway pair of
# real-shaped keys, so the guards pass and the module can be read.
#
# **`None` means CLEARED, and the identity population is cleared in full.** A
# test that imports production under this dict is asking what a deployment with
# no sign-in door configured gets. The dict used to be SILENT about the identity
# keys, so `.env` answered instead, and `test_an_unconfigured_provider_gets_no_
# origin` below went red on the first checkout that configured a client id — a
# platform test that fails because sign-in works. Silence is not a pin, and the
# census above is what keeps it from going quiet again. An arm is an explicit
# override —
# `IDENTITY_ENVIRONMENT` below is the worked one.
PRODUCTION_ENVIRONMENT: dict[str, str | None] = {
    "DEBUG": "0",
    "ALLOWED_HOSTS": "example.test",
    "SECRET_KEY": "b3a1" * 16,  # pragma: allowlist secret
    "CONNECTIONS_ENCRYPTION_KEY": "aGVsbG93b3JsZGhlbGxvd29ybGRoZWxsb3dvcmxkMTI9",
    # Third throwaway: the suite runs with the published
    # `DATABASE_PASSWORD=djb` in its environment (base reads .env), and
    # production refuses to start on it. Anything that loads production
    # settings needs a complete production environment, which is what this
    # dict is for.
    "DATABASE_PASSWORD": "throwaway-production-database-password",  # pragma: allowlist secret
    # The identity population, cleared. Kept in one block and in the order the
    # census prints, so adding the key the census names is a one-line edit.
    "BRAND_ACCENT": None,
    # The sign-in door (rung A5, design C-13). Cleared, so a production import
    # under this dict is asking what a deployment that declared nothing gets —
    # and what it gets is `hosted`, the default, which is the answer every
    # criterion in lane A is proven against. A checkout that had turned its own
    # door to `ours` in `.env` would otherwise answer for the test, and the CSP
    # census below would then be measuring that checkout rather than the
    # derivation.
    "DJB_SIGN_IN_DOOR": None,
    "GOOGLE_OAUTH_CLIENT_ID": None,
    "GOOGLE_OAUTH_CLIENT_SECRET": None,
    "GOOGLE_WORKSPACE_DOMAINS": None,
    "PRODUCT_BASE_URL": None,
    "PUBLIC_BASE_URL": None,
    "ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION": None,
    "ZITADEL_ALLOW_SELF_REGISTRATION": None,
    "ZITADEL_BROWSER_APP_NAME": None,
    "ZITADEL_CLIENT_ID": None,
    "ZITADEL_CLIENT_SECRET": None,
    "ZITADEL_DEV_USER_EMAIL": None,
    "ZITADEL_DEV_USER_PASSWORD": None,
    "ZITADEL_ISSUER": None,
    "ZITADEL_JWKS_CACHE_SECONDS": None,
    "ZITADEL_MANAGEMENT_TIMEOUT": None,
    "ZITADEL_MAX_PASSWORD_ATTEMPTS": None,
    "ZITADEL_MCP_AUDIENCE": None,
    "ZITADEL_MCP_CLIENT_NAME": None,
    "ZITADEL_MCP_RESOURCE_NAME": None,
    "ZITADEL_PAT": None,
    "ZITADEL_PROJECT_NAME": None,
    # The sign-in seam's two clocks (rung A3, design I-A §3.2). They are here
    # because the census above is DERIVED from `base.py`'s own `env.<kind>`
    # reads and these two match `IDENTITY_KEY_PREFIXES` — the same one-line
    # consequence A5's rider names for `SIGN_IN_DOOR`, arriving two rungs
    # early because the clocks land with the seam rather than with the door.
    "ZITADEL_SIGNIN_DEADLINE": None,
    "ZITADEL_SIGNIN_TIMEOUT": None,
}
