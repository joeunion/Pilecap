"""The store under test has one authority, whatever the environment exports.

`config/settings/test.py` writes the compose MinIO's address, region and
published pair as literals and pins the session token absent. These tests are
the belt on that sentence, from the two directions it can fail:

* **an exported credential wins anyway.** The first CI attempt exported a
  registry login's STS keys into the job, and every MinIO test answered
  `InvalidAccessKeyId`: the role credential reached the suite. So the settings
  are imported under a HOSTILE environment — a key, a secret, a session token
  and an endpoint that are none of the store's — and every client the suite can
  build must still resolve to the store's own address and pair, with no token.
* **the pair drifts from the container.** The literal is a copy of a published
  constant, and the container is created from `compose.yaml`'s
  `${MINIO_ROOT_USER:-minioadmin}` defaults. Two readers of one constant, pinned
  equal here, so changing either one alone is a red test rather than a store
  the suite silently cannot sign in to.

Nothing here dials the store: building a boto3 client resolves its endpoint and
its credential without a request, which is exactly the part that went wrong.
"""

from __future__ import annotations

import importlib
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import yaml
from django.conf import settings as django_settings
from django.test import override_settings

from apps.files import storage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

#: The environment a registry login, a laptop profile or a stale shell leaves
#: behind — none of it the compose store's.
HOSTILE = {
    "AWS_ACCESS_KEY_ID": "not-the-store",
    "AWS_SECRET_ACCESS_KEY": "not-the-store-either",  # pragma: allowlist secret
    "AWS_SESSION_TOKEN": "an-exported-session-token",
    "AWS_S3_ENDPOINT_URL": "http://hostile.invalid",
    "AWS_S3_REGION_NAME": "eu-hostile-1",
}

#: The names the test settings are the authority for.
PINNED = (
    "AWS_S3_ENDPOINT_URL",
    "AWS_S3_REGION_NAME",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)

DEFAULT = re.compile(r"^\$\{(?P<name>[A-Z_]+):-(?P<default>[^}]*)\}$")


@contextmanager
def _test_settings_under(environment: dict[str, str]) -> Iterator[Any]:
    """`config.settings.test`, re-executed with `environment` exported.

    Settings are read at import, so the only honest way to see what the suite
    would get under a hostile environment is to import the module under one.
    `base` is reloaded first because `test` star-imports it; both are reloaded
    again on the way out so nothing downstream sees the hostile values.
    `django.conf.settings` is a separate object and is untouched throughout.
    """
    base = importlib.import_module("config.settings.base")
    test = importlib.import_module("config.settings.test")
    try:
        with mock.patch.dict(os.environ, environment):
            importlib.reload(base)
            yield importlib.reload(test)
    finally:
        importlib.reload(base)
        importlib.reload(test)


def _frozen(client: Any) -> tuple[str, str, str | None]:
    credentials = client._get_credentials().get_frozen_credentials()
    return (credentials.access_key, credentials.secret_key, credentials.token)


def test_an_exported_credential_and_endpoint_never_reach_the_store_under_test() -> None:
    # django-storages ships no `py.typed` marker; the backend is only instantiated here.
    from storages.backends.s3 import S3Storage  # type: ignore[import-untyped]

    with _test_settings_under(HOSTILE) as under_test:
        resolved = {name: getattr(under_test, name, "<unset>") for name in PINNED}

    assert resolved == {
        "AWS_S3_ENDPOINT_URL": "http://127.0.0.1:9000",
        "AWS_S3_REGION_NAME": "us-east-1",
        "AWS_ACCESS_KEY_ID": "minioadmin",
        "AWS_SECRET_ACCESS_KEY": "minioadmin",  # pragma: allowlist secret
        "AWS_SESSION_TOKEN": None,
    }

    # AND EVERY CLIENT THE SUITE CAN BUILD CARRIES THEM, with the hostile
    # environment still exported — the one seam (`apps/core/health.py` builds
    # its probe the same way), and django-storages' backend, which is the one
    # that would fall back to an exported session token if the setting were
    # missing.
    with mock.patch.dict(os.environ, HOSTILE), override_settings(**resolved):
        seam = storage.client()
        backend = S3Storage(bucket_name="the-store").connection.meta.client

    store = ("minioadmin", "minioadmin", None)
    assert _frozen(seam) == store
    assert _frozen(backend) == store
    assert seam.meta.endpoint_url == "http://127.0.0.1:9000"
    assert backend.meta.endpoint_url == "http://127.0.0.1:9000"
    assert seam.meta.region_name == "us-east-1"


def test_the_pinned_pair_and_port_are_compose_yamls_published_minio_defaults() -> None:
    compose = yaml.safe_load((Path(django_settings.BASE_DIR) / "compose.yaml").read_text())
    minio = compose["services"]["minio"]
    published: dict[str, str] = {}
    for name in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
        match = DEFAULT.match(str(minio["environment"][name]))
        assert match is not None, f"{name} is no longer `${{{name}:-<default>}}` in compose.yaml"
        published[name] = match.group("default")

    under_test = importlib.import_module("config.settings.test")
    assert (under_test.AWS_ACCESS_KEY_ID, under_test.AWS_SECRET_ACCESS_KEY) == (
        published["MINIO_ROOT_USER"],
        published["MINIO_ROOT_PASSWORD"],
    )
    # The endpoint names the port compose publishes the S3 API on, on loopback.
    assert "127.0.0.1:9000:9000" in [str(port) for port in minio["ports"]]
    assert under_test.AWS_S3_ENDPOINT_URL == "http://127.0.0.1:9000"
