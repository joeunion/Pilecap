"""A refusal's sentences are read by people: they carry no backticked key.

The registry's `fact` is what the published contract and a face show a person
who was refused. A machine token in it — "`current_version` is the version it
has now" — is a word the reader was never taught: the fact is said in words, and
the key it names rides `wire_extra` for the machine. House rule 73 reads copy
modules only, so this reads every registered sentence, discovered from the live
registry with every installed app's registering modules loaded.
"""

from __future__ import annotations

import importlib
import importlib.util

from django.apps import apps as django_apps

from apps.core.exceptions import StaleVersion, _registry, wire_refusal

#: The modules a refusal is registered in, beside the class that raises it.
REGISTERING_MODULES = ("exceptions", "services", "selectors", "api", "mcp", "activities")


#: The mount modules that register refusals of their own (the REST door's body
#: refusal is `config/api.py`'s), imported beside the apps' so the read does not
#: depend on which test built the application first.
MOUNT_MODULES = ("config.api", "config.mcp")


def _load_every_registration() -> None:
    """Import every installed app's registering modules and the mounts, so the registry is whole."""
    for dotted in MOUNT_MODULES:
        importlib.import_module(dotted)
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        for module in REGISTERING_MODULES:
            dotted = f"{config.name}.{module}"
            if importlib.util.find_spec(dotted) is not None:
                importlib.import_module(dotted)


#: A sentence that still carries a token, registered where the change that swept
#: the others could not write: named here so it cannot grow a sibling, and so its
#: removal is a one-line diff (the test fails when the entry goes stale).
STILL_TOKENED: dict[str, str] = {}


def test_no_registered_fact_carries_a_backticked_key() -> None:
    _load_every_registration()
    assert len(_registry) > 20, "the registry is nearly empty — this reads nothing"
    tokened = {code: entry.fact for code, entry in _registry.items() if "`" in entry.fact}
    assert {code: fact for code, fact in tokened.items() if code not in STILL_TOKENED} == {}
    stale = sorted(set(STILL_TOKENED) - set(tokened))
    assert stale == [], f"no longer tokened — remove from STILL_TOKENED: {stale}"


def test_a_stale_write_says_the_version_in_words_and_carries_it_as_a_key() -> None:
    body = wire_refusal(StaleVersion(current_version=1_234))
    assert "1234" in body["detail"], body
    assert "`" not in body["detail"], body
    assert body["current_version"] == 1_234
