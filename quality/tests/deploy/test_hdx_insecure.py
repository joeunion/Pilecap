"""The ClickStack client skips certificate checks only when it dials this machine."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

HDX = Path(__file__).resolve().parents[3] / "deploy" / "observability" / "hyperdx" / "hdx.py"


@pytest.fixture(scope="module")
def hdx() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hdx_under_test", HDX)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _client(hdx: ModuleType, base: str, connect: str) -> object:
    return hdx.Client(
        base, "observer", "wall", "you@example.com", "pw", insecure=True, connect=connect
    )


@pytest.mark.parametrize(
    ("base", "connect"),
    [("https://o11y.example.com", ""), ("https://o11y.localhost:8453", "10.0.0.7:8453")],
)
def test_an_unverified_context_is_refused_off_this_machine(
    hdx: ModuleType, base: str, connect: str
) -> None:
    with pytest.raises(hdx.HdxError, match="laptop stack only"):
        _client(hdx, base, connect)


def test_a_loopback_dial_may_skip_verification(
    hdx: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hdx.Client, "_login", lambda self, email, password: None)
    client: Any = _client(hdx, "https://o11y.localhost:8453", "127.0.0.1:8453")
    assert client._insecure is True
