"""Which addresses an outbound webhook may be sent to, by address class (ADR events-5)."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Iterable

import httpx
from django.conf import settings
from django.utils.module_loading import import_string

from apps.core.exceptions import Invalid

Address = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolve = Callable[[str], Iterable[str]]

#: Every class of target this module refuses, each with the sentence its refusal carries.
REFUSED_CLASSES: dict[str, str] = {
    "not_https": "The address must use https.",
    "no_host": "The address names no host.",
    "local_name": "The host is a local name (localhost, *.localhost or *.internal).",
    "unresolvable": "The host does not resolve to any address.",
    "unspecified": "The host is or resolves to an unspecified address.",
    "loopback": "The host is or resolves to a loopback address.",
    "link_local": "The host is or resolves to a link-local address.",
    "multicast": "The host is or resolves to a multicast address.",
    "private": "The host is or resolves to a private address.",
    "reserved": "The host is or resolves to a reserved address.",
    "not_global": "The host is or resolves to an address that is not publicly routable.",
}

#: The host suffixes that name the machine or its private network, never a subscriber.
LOCAL_SUFFIXES = (".localhost", ".internal")

#: The shapes `inet_aton` reads as IPv4 besides dotted quads — `2130706433`, `0x7f.1`.
_LEGACY_IPV4 = re.compile(r"^[0-9a-fx.]+$")


def resolve_host(host: str) -> list[str]:
    """Every address `host` resolves to, through `settings.WEBHOOK_TARGET_RESOLVER` if named."""
    stand_in = getattr(settings, "WEBHOOK_TARGET_RESOLVER", "")
    if stand_in:
        resolved: list[str] = import_string(stand_in)(host)
        return resolved
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return []
    return [str(info[4][0]) for info in infos]


def _spelled_address(host: str) -> Address | None:
    """The address `host` spells literally, legacy IPv4 forms included; `None` for a name."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if _LEGACY_IPV4.match(host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def address_class(address: Address) -> str | None:
    """The refused class `address` falls in, an IPv4-mapped IPv6 judged as its IPv4; else `None`."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    checks = (
        ("unspecified", address.is_unspecified),
        ("loopback", address.is_loopback),
        ("link_local", address.is_link_local),
        ("multicast", address.is_multicast),
        ("private", address.is_private),
        ("reserved", address.is_reserved),
        ("not_global", not address.is_global),
    )
    return next((name for name, refused in checks if refused), None)


def target_class(url: str, *, resolve: Resolve | None = None, dns: bool = True) -> str | None:
    """The refused class of `url` or `None`; `dns=False` judges only what the URL spells."""
    allowed_private = bool(settings.WEBHOOK_PRIVATE_TARGETS_ALLOWED)
    try:
        parsed = httpx.URL(url.strip())
    except (httpx.InvalidURL, TypeError):
        return "no_host"
    if parsed.scheme != "https" and not (allowed_private and parsed.scheme == "http"):
        return "not_https"
    host = parsed.host.rstrip(".").lower()
    if not host:
        return "no_host"
    if allowed_private:
        return None
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return "local_name"
    literal = _spelled_address(host)
    if literal is not None:
        return address_class(literal)
    if not dns:
        return None
    addresses = list((resolve or resolve_host)(host))
    if not addresses:
        return "unresolvable"
    for raw in addresses:
        found = _spelled_address(raw.split("%", 1)[0])
        refused = "unresolvable" if found is None else address_class(found)
        if refused is not None:
            return refused
    return None


def refuse_private_target(url: str, *, resolve: Resolve | None = None, dns: bool = True) -> None:
    """Raise `Invalid` on `url` naming its refused class; return when it may be delivered to."""
    refused = target_class(url, resolve=resolve, dns=dns)
    if refused is not None:
        raise Invalid({"url": [REFUSED_CLASSES[refused]]})
