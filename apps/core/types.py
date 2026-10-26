"""The shapes that cross the workflow boundary for `apps.core`'s own machinery.

Stdlib only, and that is the whole contract of a `types.py` here: a workflow
argument or result must be replayable years from now, so nothing in this module
may import Django, the ORM, or anything that reads the world.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.core.roads import road


@dataclass
class ProbeOutcome:
    """What one run of the integrations prober found — **or could not find**.

    Two fields and the second is the one that matters. `statuses` is the census
    as `{key: status}`, which is the run's own report: a run whose values are all
    `configured` is the healthy steady state and reads as one at a glance in the
    Temporal UI.

    `incomplete` is why the census did not finish, and it is empty when it did.
    It exists because the first version of this workflow had nowhere to put that
    answer and therefore FAILED instead — which is exactly backwards for a rot
    detector. A standing probe that dies when the thing it probes is unreachable
    goes silent at the only moment anybody needed it: the run row says `failed`,
    nobody receives the census, and the outage the probe existed to notice is
    the reason nothing was noticed.

    So "the probe could not finish" is DATA the run carries, not an exception
    the run dies of. A reader — or an alert on the run's result — can tell the
    three states apart: everything configured, something is a fake, and nobody
    could look.
    """

    #: `{integration key: status value}`. Empty when `incomplete` is set.
    statuses: dict[str, str] = field(default_factory=dict)

    #: Why the census did not finish. Empty string when it did.
    incomplete: str = ""

    @property
    def is_complete(self) -> bool:
        return not self.incomplete


# No Widget example: Widget does not adopt this road yet, so the example is an owner's purge.
@road("sweep_result", example="apps/connections/services.py::purge_inbound_webhooks")
@dataclass(frozen=True)
class Swept:
    """What one sweep walked, and how many rows of it went.

    **The population shape ADR core-22 files a sweep under** (the L6 ruling of
    2026-08-26). A sweep does not act on *an* object, it acts on a population,
    and the honest audit row says so: `object_type` is the swept model's label,
    `object_id` is NULL, and the count is the number below. A row naming one
    arbitrary victim out of nine hundred would be worse than a row naming none,
    because it reads as a single deletion somebody could go and look up.

    `label` is a lazy model reference — the string `apps.Model` form Django's
    own `ForeignKey("accounts.ApiToken")` uses, and `AuditEntry.actor_token`
    with it — because this module is stdlib-only by contract: a `types.py` here
    may not import the ORM. The census test resolves every declared label
    through `django.apps`, so a renamed model fails by name rather than filing
    rows under a string that stopped meaning anything.

    A blank label is refused by `core.service._declared_object` rather than
    written: an `object_type` of `""` names nothing, which is the exact defect
    this declaration closes.
    """

    label: str
    count: int

    @property
    def audit_object(self) -> tuple[str, None]:
        """The `(label, pk)` pair `core.service._object_of` reads. The pk is NULL."""
        return (self.label, None)
