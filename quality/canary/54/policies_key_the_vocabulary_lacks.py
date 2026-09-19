"""Planted: a `POLICIES` entry for a key the vocabulary does not hold (clause a).

`gadget.polish` is not a derived key — `Gadget` yields create, read, update and
delete and nothing else — and no `ACTION_PROSE` declares it here. So this is a
predicate for a capability nobody can be given: `require` resolves the key,
finds it in no vocabulary, and never reaches the function below.

**And nothing else can see it.** `vocabulary()` reads the policy registry only
for keys it has already derived, so a key that lives in `POLICIES` alone is
absent from the vocabulary, absent from `non_conforming()`, absent from every
pinned census, and the whole suite stays green over it. That is why this half is
a finding rather than a note: the defect's own shape is that it is invisible.
"""


def _yes(actor, obj=None):
    return True


POLICIES = {"gadget.polish": _yes}
