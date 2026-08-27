"""The scope-family freeze census — the one platform file a PRODUCT appends to.

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

__all__ = ["FROZEN_FAMILIES", "SANCTIONED_RENAMES"]


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
FROZEN_FAMILIES: tuple[str, ...] = (
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
    "roles",
    "runs",
    # ADR search-2. The third of a four-key frame's ratified keys
    # (`design-agreements.md`: files/search/usage/devices). Frozen the day the
    # door shipped, like every other key here: `search:read` is what a token
    # holding it is trusted with, and there is no `search:write` because there
    # is no write door — indexing is spine-fed and service-only.
    "search",
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
    "widgets",
)

#: The departures an owner has ruled: a retired key, and what it became.
#:
#: One entry, and it is meant to stay one. `organizations` shipped as a single
#: family covering the org tree, the role grants and the invitation lifecycle;
#: the owner's ruling of 2026-08-24 (`docs/product/design-agreements.md`, "the
#: three-way scope split") split it three ways after FT-1′ demonstrated from the
#: persona seat that the narrowest token which did any one of those jobs could
#: do all three.
#:
#: **What this is NOT: a compatibility shim.** `organizations:write` is refused,
#: not translated. An alias would go on granting all three capabilities forever,
#: which is exactly the ceiling the ruling retires. What the entry buys is a
#: FOLLOWABLE refusal — `ceiling_from_request` names the successors, so the next
#: attempt can be right — and a record of which rename was sanctioned, so that
#: `family_freeze_findings` can tell a ruled migration from an accident.
SANCTIONED_RENAMES: dict[str, tuple[str, ...]] = {
    "organizations": ("org-structure", "roles", "invitations"),
}
