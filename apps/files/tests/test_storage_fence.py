# census: cross-app population=apps/**/*.py for imports of the object-store SDK
"""Who is allowed to speak to an object store. **A pin, so the answer is a diff.**

ADR files-2 ruled a storage wall, landed as house rule 48, with canaries, run
by the house-rules engine. This module is not that rule and never was: it is
the CENSUS the rule was written against, pinned by hand from inside the app
that owns the seam, and it stays because it fails **by name** where the rule
fails by clause. Rule 48's own scope block says so — "The pin stays — it
fails by NAME, from inside the app that owns the seam, and this rule is the
other three clauses plus the fifth door."

**Two members, and the second one was this pin's original finding.** An
earlier cycle reconciliation listed the storage seams the wall had to dispose
of as three: `config/settings`' `STORAGES`, the core app's `storage.py` key
builder and `apps/exports`' `default_storage` writes. `apps/core/health.py::check_object_storage`
was a **fourth** that post-dated the list — legitimate, because a readiness
probe has to reach the organ it reports on and `core` importing `files`
would be an upward import house rule 7 refuses — and it was handed up here
to allow-list, which rule 48 now does by path and with the reason.

**All three of the reconciliation's seams are disposed of, which is why the pin
reads two and not five** (the list above is kept as history, not as a
description of this tree): `apps/exports` was re-pointed onto
`files.services.store_bytes`; the core app's `storage.py` and its
`tenant_prefixed_key` were **deleted whole** once that took the
last caller, so the key builder this file used to name no longer exists; and
`config/settings`' `STORAGES` is fenced by rule 48's fifth clause rather than by
this pin, which walks `apps/` only.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

from apps.core.tests.tree_census import source_text, vanishing_source_file

#: An import of the AWS SDK, however it is spelled.
IMPORTS_THE_SDK = re.compile(r"^\s*(?:from|import)\s+(?:boto3|botocore)\b", re.MULTILINE)

#: Every module under `apps/` that may speak to an object store, and why. A file
#: joining this set is a decision; a file joining it silently is the leak the
#: whole wall exists to prevent.
ALLOWED: dict[str, str] = {
    "apps/files/storage.py": (
        "the seam itself (ADR files-2): the one place a bucket is named, the one "
        "place a URL is signed, and the one place bytes are read."
    ),
    "apps/core/health.py": (
        "the readiness probe. `/readyz` reports on object storage as "
        "an organ, and `core` cannot import `files` — that is an upward import "
        "house rule 7 refuses. It heads the bucket and writes nothing. THE FOURTH "
        "SEAM an earlier reconciliation's three-seam list did not name; rule 48's "
        "`allow_import` now carries the same entry and the same reason."
    ),
}

#: Tests are outside the wall by construction — including this one, which has to
#: say the names to count them.
EXCLUDED_DIRECTORY = "tests"


def _modules_importing_the_sdk() -> set[str]:
    root = Path(settings.BASE_DIR)
    found: set[str] = set()
    for path in sorted((root / "apps").rglob("*.py")):
        if EXCLUDED_DIRECTORY in path.parts:
            continue
        if IMPORTS_THE_SDK.search(source_text(path)):
            found.add(str(path.relative_to(root)))
    return found


def test_only_the_named_modules_speak_to_an_object_store() -> None:
    """The pin. A new importer under `apps/` fails here, by name."""
    assert _modules_importing_the_sdk() == set(ALLOWED)


def test_every_allowed_module_is_still_an_importer() -> None:
    """The other direction: an allow-list entry nobody uses is a fence in a field.

    It goes stale the day a module stops importing the SDK, and a stale entry is
    permission nobody asked for sitting in the census the wall will be built from.
    """
    assert set(ALLOWED) <= _modules_importing_the_sdk()


def test_every_entry_carries_a_reason_somebody_can_disagree_with() -> None:
    """A census whose entries say nothing is a hand-list wearing a census's clothes."""
    for module, reason in ALLOWED.items():
        assert len(reason) > 40, module


def test_the_fence_census_tolerates_a_file_that_vanishes_at_open() -> None:
    """The falsifier for the tolerant read: a vanishing file raises `FileNotFoundError`
    unless the read tolerates it.

    The plant imports no SDK, so passing means it was skipped.
    """
    with vanishing_source_file() as planted:
        assert _modules_importing_the_sdk() is not None
        assert not planted.exists(), "the census never opened the plant — this drove nothing"
