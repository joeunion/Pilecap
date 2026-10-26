"""One case per class in `targets.REFUSED_CLASSES`, each refusal naming its class and no address."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from typing import Any

import pytest
from django.test import override_settings

from apps.core.exceptions import Invalid
from apps.events import targets

PUBLIC = "93.184.215.14"

#: The shipped resolver, held before `conftest.resolved_hosts` stands in for it.
SYSTEM_RESOLVE = targets.resolve_host


def resolver(*addresses: str) -> targets.Resolve:
    """A resolver answering `addresses` for every host."""

    def resolve(host: str) -> Iterable[str]:
        return list(addresses)

    return resolve


#: (class, url, what the stand-in resolver answers) — one row per refused class at least.
CASES: list[tuple[str, str, tuple[str, ...]]] = [
    ("not_https", "http://hooks.example.com/h", (PUBLIC,)),
    ("not_https", "ftp://hooks.example.com/h", (PUBLIC,)),
    ("no_host", "https:///h", (PUBLIC,)),
    ("local_name", "https://localhost/h", (PUBLIC,)),
    ("local_name", "https://LOCALHOST./h", (PUBLIC,)),
    ("local_name", "https://admin.localhost/h", (PUBLIC,)),
    ("local_name", "https://metadata.google.internal/h", (PUBLIC,)),
    ("unresolvable", "https://nowhere.example/h", ()),
    ("unspecified", "https://0.0.0.0/h", (PUBLIC,)),
    ("unspecified", "https://[::]/h", (PUBLIC,)),
    ("loopback", "https://127.0.0.1/h", (PUBLIC,)),
    ("loopback", "https://2130706433/h", (PUBLIC,)),
    ("loopback", "https://[::1]/h", (PUBLIC,)),
    ("loopback", "https://[::ffff:127.0.0.1]/h", (PUBLIC,)),
    ("link_local", "https://169.254.169.254/latest/meta-data/", (PUBLIC,)),
    ("link_local", "https://[fe80::1]/h", (PUBLIC,)),
    ("link_local", "https://[::ffff:169.254.169.254]/h", (PUBLIC,)),
    ("multicast", "https://224.0.0.1/h", (PUBLIC,)),
    ("multicast", "https://[ff02::1]/h", (PUBLIC,)),
    ("private", "https://10.0.0.1/h", (PUBLIC,)),
    ("private", "https://192.168.1.1/h", (PUBLIC,)),
    ("private", "https://172.16.0.1/h", (PUBLIC,)),
    ("private", "https://[fd00::1]/h", (PUBLIC,)),
    ("private", "https://[::ffff:10.0.0.1]/h", (PUBLIC,)),
    ("private", "https://inside.example.com/h", ("10.1.2.3",)),
    ("private", "https://mixed.example.com/h", (PUBLIC, "192.168.0.7")),
    ("loopback", "https://rebind.example.com/h", ("::1",)),
    ("private", "https://[2001:db8::1]/h", (PUBLIC,)),
    ("reserved", "https://[4000::1]/h", (PUBLIC,)),
    ("private", "https://240.0.0.1/h", (PUBLIC,)),
    ("not_global", "https://100.64.0.1/h", (PUBLIC,)),
]


def test_every_declared_class_has_a_case() -> None:
    covered = {refused for refused, _, _ in CASES}
    assert covered == set(targets.REFUSED_CLASSES), set(targets.REFUSED_CLASSES) ^ covered


@pytest.mark.parametrize(("refused", "url", "answers"), CASES, ids=[c[1] for c in CASES])
def test_each_refused_class_is_named_and_no_address_is(
    refused: str, url: str, answers: tuple[str, ...]
) -> None:
    assert targets.target_class(url, resolve=resolver(*answers)) == refused

    with pytest.raises(Invalid) as caught:
        targets.refuse_private_target(url, resolve=resolver(*answers))

    [sentence] = caught.value.errors["url"]
    assert sentence == targets.REFUSED_CLASSES[refused]
    spoken = [token for token in sentence.replace(",", " ").split() if _is_address(token)]
    assert spoken == [], f"the refusal spoke an address: {spoken}"
    for answer in answers:
        assert answer not in sentence


def _is_address(token: str) -> bool:
    try:
        ipaddress.ip_address(token.strip("()."))
    except ValueError:
        return False
    return True


def test_a_public_https_target_is_accepted() -> None:
    assert targets.target_class("https://hooks.example.com/h", resolve=resolver(PUBLIC)) is None
    targets.refuse_private_target("https://hooks.example.com/h", resolve=resolver(PUBLIC))


def test_without_dns_a_name_is_not_resolved_and_a_literal_still_refuses() -> None:
    def explode(host: str) -> Iterable[str]:
        raise AssertionError(f"resolved {host} with dns off")

    assert targets.target_class("https://inside.example.com/h", resolve=explode, dns=False) is None
    assert targets.target_class("https://10.0.0.1/h", resolve=explode, dns=False) == "private"
    assert targets.target_class("http://hooks.example.com/h", resolve=explode, dns=False) == (
        "not_https"
    )


@override_settings(WEBHOOK_PRIVATE_TARGETS_ALLOWED=True)
def test_the_laptop_valve_accepts_plain_http_to_localhost_without_resolving() -> None:
    def explode(host: str) -> Iterable[str]:
        raise AssertionError(f"resolved {host} with private targets allowed")

    assert targets.target_class("http://localhost:9000/hook", resolve=explode) is None
    assert targets.target_class("http://10.0.0.1/hook", resolve=explode) is None
    assert targets.target_class("ftp://localhost/hook", resolve=explode) == "not_https"


def test_a_deployment_resolves_through_the_system_resolver(
    monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    """With no stand-in named, `resolve_host` asks `getaddrinfo`, and a failure is no address."""
    settings.WEBHOOK_TARGET_RESOLVER = ""
    monkeypatch.setattr(targets, "resolve_host", SYSTEM_RESOLVE)
    asked: list[str] = []

    def getaddrinfo(host: str, *_: object, **__: object) -> list[tuple[object, ...]]:
        asked.append(host)
        if host == "gone.example":
            raise socket.gaierror("no such host")
        return [(None, None, None, "", ("10.0.0.2", 0)), (None, None, None, "", ("::1", 0, 0, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    assert targets.resolve_host("hooks.example.com") == ["10.0.0.2", "::1"]
    assert targets.resolve_host("gone.example") == []
    assert targets.target_class("https://hooks.example.com/h") == "private"
    assert asked == ["hooks.example.com", "gone.example", "hooks.example.com"]
