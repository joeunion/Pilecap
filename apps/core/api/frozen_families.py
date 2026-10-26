"""The scope-family freeze census — the template's record, unioned with a product's drawer.

**Why this is its own module.** Everything in `scopes.py` is machinery: the
derivation, the predicate, the refusal. These two values are a **record**, and
they are the record a cloned product has to write into. `scopes.py`'s own
sentence about `FROZEN_FAMILIES` says so — *"a key joins this list in the commit
that ships it"* — and a product ships its first door on day one.

That is what makes this file different from every other platform file, and it
is why it is the **one enumerated exclusion from the platform partition's input
closure** (`docs/product/partition-closure.md` §3, disposition D1;
`quality/partition.yaml` carries the exclusion and the reason).

The mechanism, in one paragraph, because a file that is treated specially should
say why where somebody editing it will read it: the partition skips the
platform's pytest suite when a banked verdict's key still matches everything
that suite reads. If this list were inside the closure, a product appending its
own family here would move the closure hash on its FIRST DOOR: a planted
product app produced a false red on three
in-closure tests, which a clone could not clear without editing in-closure
files. Out of the closure, the append still reaches the partition — through the
**discovery digest**, whose `scope_families` section serializes both the live
families and this ledger. So the re-run the append triggers is the same re-run
the new family already triggered, and the product's edit lands in its own
commit, in a file it is meant to edit.

**Nothing about the freeze itself changes.** `scopes.py` imports both names and
re-exports them unchanged, `family_freeze_findings` reads them exactly as it
did, and `apps/accounts/tests/test_scopes.py` pins them exactly as it did. A
platform family shipped and not written down here still fails by name, in the
commit that ships it. What moved is which file the record lives in — and the
generalized rule that move came from (§5's doctrine): *a central ledger that
products must append to either lives out-of-closure as a data module that
re-enters the skip key through the digest, or the assertion scopes its
quantifier to the lockfile population.*
"""

from __future__ import annotations

from pathlib import Path

import yaml
from django.core.exceptions import ImproperlyConfigured

__all__ = [
    "DRAWER",
    "FROZEN_FAMILIES",
    "SANCTIONED_RENAMES",
    "DeclaredBy",
    "Released",
    "drawer_families",
    "with_drawer",
]


class Released(tuple[str, ...]):
    """A sanctioned departure whose old key had NO HOLDERS, so its word is given back.

    The successors, exactly as a plain entry carries them — this IS the tuple,
    so every reader that walks `SANCTIONED_RENAMES` sees the same successors —
    and one fact more, carried by the type rather than by a second record that
    could disagree with it: nobody could have minted a token on the old key, so
    the freeze has no holder to protect. A product may therefore reclaim the old
    word as a family of its own: `family_freeze_findings` does not call it
    "live again", and a token asking for it is told about the successor only
    while no app here declares it.

    A plain tuple entry is the other kind — a departure from keys people did
    hold (`organizations`) — and the freeze keeps refusing its word forever.
    """

    __slots__ = ()


class DeclaredBy(str):
    """A frozen family whose declaring app a deployment may leave out — the app named.

    The key itself, exactly as a plain entry is (this IS the string, so every
    reader that walks `FROZEN_FAMILIES` sees the same word), and one fact more,
    carried by the type: WHICH app declares it. A deployment that switched that
    app off (`DJB_DISABLED_APPS` — the app's own `optional = True`, or a
    `depends_on` reaching one that is) has no door for the family by its own
    choice, and `family_freeze_findings` does not call that a vanished key;
    the freeze still holds the word, so the app switched back on answers it.
    """

    app: str

    def __new__(cls, family: str, *, app: str) -> DeclaredBy:
        made = super().__new__(cls, family)
        made.app = app
        return made


#: Every family key a minted token could already be carrying.
#:
#: **Written down rather than derived, and that is the point.** A census derived
#: from `families()` would be a copy of the very thing it exists to remember: it
#: would agree with any rename the moment the rename landed. What makes this
#: useful is that it is a record of the past, kept by hand, in a diff a human
#: reads.
#:
#: **A key joins this list in the commit that ships it.** Growing the vocabulary
#: is free and nothing here refuses a new family; what keeps the list current is
#: `apps/accounts/tests/test_scopes.py`, which pins it equal to the live
#: vocabulary, so a family shipped and not written down fails by name.
CORE_FAMILIES: tuple[str, ...] = (
    "auth",
    "connections",
    # ADR comms-9's push half. The fourth of a four-key frame's
    # ratified keys (`design-agreements.md`, RUL-1: files/search/usage/devices).
    # A NEW family rather than a corner of `messaging`, because the two are not
    # the same trust: `messaging:write` is "may contact a person" and
    # `devices:write` is "may keep the push address book", which reaches nobody
    # by itself — a registration is not a send, and an agent trusted to keep an
    # address book is not thereby trusted to mail everybody in it.
    # `devices:read` is derivable and reaches nothing: this family shipped a
    # registration door and a retirement door and no list, which is exactly the
    # shape `usage:write` has below. Frozen from the day the door shipped, like
    # every other key here.
    "devices",
    # The import road's family: bringing rows in from a file. `djb_imports:read`
    # is reading an import and its preview, `djb_imports:write` is staging,
    # applying and cancelling one. Shipped at 2.4.0 as `imports`; moved at 2.4.1
    # to the platform's namespace word while no product had taken that release,
    # so a product's own `imports` app can own `imports` — the departure is
    # recorded in SANCTIONED_RENAMES below.
    "djb_imports",
    # The attach owner for notes. `djb_notes:read` is reading what people wrote
    # about a record, `djb_notes:write` is writing, correcting and archiving it —
    # and neither reaches the record itself. Shipped at 2.4.0 as `notes`; moved
    # at 2.4.1 to the platform's namespace word while no product had taken that
    # release — the departure is recorded in SANCTIONED_RENAMES below.
    "djb_notes",
    # The attach owner for tags. `djb_tags:read` is reading the tenant's words
    # and the words a row carries; `djb_tags:write` is putting a word on a row or
    # taking it off (and, for an administrator of the whole tenant, coining,
    # renaming and retiring one). Shipped at 2.4.0 as `tags`; moved at 2.4.1 to
    # the platform's namespace word while no product had taken that release —
    # the departure is recorded in SANCTIONED_RENAMES below.
    "djb_tags",
    "events",
    # A NEW family rather than a rename: taking a copy of your own
    # data out of the product is a capability no existing key covered, and
    # `exports:read` / `exports:write` say what a token holding them is trusted
    # with to somebody reading the string with no API around it. Frozen from the
    # day it shipped, like every other key here.
    "exports",
    # ADR files-2. The fourth of a four-key frame's ratified keys
    # (`design-agreements.md`: files/search/usage/devices), and the DEFAULT half
    # of the choosing pattern working: the plural noun of the section's primary
    # resource, and `a file` is a noun a caller already has. `files:read` and
    # `files:write` say what a token holding them is trusted with — see the
    # documents, and put one in. Frozen the day the door shipped, like every other
    # key here.
    "files",
    "invitations",
    "messaging",
    "org-structure",
    # The worked customer face's own family (`apps/example_portal`):
    # `portal_requests:read` is reading the requests a customer sent,
    # `portal_requests:write` is sending one. Frozen the day the door shipped,
    # like every other key here.
    DeclaredBy("portal_requests", app="example_portal"),
    "roles",
    "runs",
    # ADR search-2. The third of a four-key frame's ratified keys
    # (`design-agreements.md`: files/search/usage/devices). Frozen the day the
    # door shipped, like every other key here: `search:read` is what a token
    # holding it is trusted with, and there is no `search:write` because there
    # is no write door — indexing is spine-fed and service-only.
    "search",
    "socket-tickets",
    "tenant-settings",
    "tokens",
    # ADR usage-1. A NEW family, and the mildest exception the
    # choosing pattern has: the default is the plural noun of the section's
    # primary resource and `usage` has no plural that means anything, which is
    # already house rule 16's recorded exception for the app of the same name.
    # `usage:read` says what a token holding it is trusted with — reading what
    # this account has consumed. `usage:write` is derivable and reaches nothing:
    # the section is read-only by design, so no route and no tool exists for it
    # to satisfy. Frozen from the day it shipped, like every other key here.
    "usage",
    "users",
    DeclaredBy("widgets", app="example"),
)

#: The departures an owner has ruled: a retired key, and what it became.
#:
#: Four entries, of two kinds. `organizations` shipped as a single family
#: covering the org tree, the role grants and the invitation lifecycle; the
#: owner's ruling of 2026-08-24 (`docs/product/design-agreements.md`, "the
#: three-way scope split") split it three ways after FT-1′ demonstrated from the
#: persona seat that the narrowest token which did any one of those jobs could
#: do all three.
#:
#: The other three are a different case: a RELEASED departure, a departure with
#: no holder, marked by its type (`Released`). `imports`, `notes` and `tags`
#: shipped at 2.4.0 and moved to their `djb_` words at 2.4.1 on the owner's
#: ruling of 2026-09-29 (the platform apps a release adds take names no product
#: spells). No product had taken 2.4.0, so no token outside this repository can
#: hold the old keys, and the words are GIVEN BACK to products: a product's own
#: `notes` app may tag `notes` and own `notes:read` outright. The entries stay
#: so that a template developer's own dev token, while no app here owns the old
#: word, is told what to ask for instead of being refused blankly.
#:
#: **What this is NOT: a compatibility shim.** `organizations:write` is refused,
#: not translated. An alias would go on granting all three capabilities forever,
#: which is exactly the ceiling the ruling retires. What the entry buys is a
#: FOLLOWABLE refusal — `ceiling_from_request` names the successors, so the next
#: attempt can be right — and a record of which rename was sanctioned, so that
#: `family_freeze_findings` can tell a ruled migration from an accident.
SANCTIONED_RENAMES: dict[str, tuple[str, ...]] = {
    "organizations": ("org-structure", "roles", "invitations"),
    # The owner's non-colliding-names ruling of 2026-09-29: the three platform
    # apps' families take the namespace word their labels carry. RELEASED,
    # because no product had taken the release that shipped the old keys: the
    # words are given back to products.
    "imports": Released(("djb_imports",)),
    "notes": Released(("djb_notes",)),
    "tags": Released(("djb_tags",)),
}


#: A product's own frozen families; rule 95 keeps it out of this file.
DRAWER = "quality/local/frozen_families.yaml"

_ROOT = Path(__file__).resolve().parents[3]


def drawer_families(path: Path) -> tuple[str, ...]:
    """The family keys the drawer at `path` freezes, under `families:`; absent is none."""
    if not path.is_file():
        return ()
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    words = loaded.get("families") if isinstance(loaded, dict) else None
    if (
        not isinstance(loaded, dict)
        or set(loaded) - {"families"}
        or not isinstance(words, list)
        or not all(isinstance(word, str) and word for word in words)
    ):
        raise ImproperlyConfigured(
            f"{DRAWER} is not `families:` and a list of family keys — the product's "
            "frozen families are read from it, so a shape nobody can read is refused."
        )
    return tuple(words)


def with_drawer(core: tuple[str, ...], path: Path) -> tuple[str, ...]:
    """The core tuple, then each family the drawer at `path` adds that it does not hold."""
    return (*core, *(family for family in drawer_families(path) if family not in core))


#: The core tuple, then the product drawer's families: the census every reader walks.
FROZEN_FAMILIES = with_drawer(CORE_FAMILIES, _ROOT / DRAWER)
