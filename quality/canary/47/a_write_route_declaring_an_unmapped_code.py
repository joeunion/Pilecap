

# --- planted (house rule 47's canary) ------------------------------------------
#
# THE CANARY CARRIES ITS OWN DISEASE. It registers its own refusal code and
# declares that — never a code the product owns — so nothing a rung does to a
# real refusal can cure it.
#
# WHY, WITH THE DATE (corrected at the merge). This fixture first
# declared `session_required`, which was the live drop the rule was born
# against. landed `CODE_STATUS[SessionRequired.code]` in the same merge
# window, published that code, and killed both of this rule's canaries at once —
# exit 2 on the merged tree. That is the class exactly: **an instrument may
# not depend on a patient staying ill**, which is the rule adopted when rule 5's
# last real-app plant was retired for a trigger whose condition was "the day
# `apps/realtime` gets healthier". A canary pointed at a real defect is a canary
# with an expiry date nobody wrote down, and it expires as exit 2 on somebody
# else's rung.
#
# WHAT MAKES THIS ONE PERMANENT. `canary_unpublished` is REGISTERED — through
# the same `register_refusal` every real code goes through, with the same fact
# and remedies the grammar demands, so rule 41 is satisfied and stays SILENT on
# it, which is the whole point: 41 asks whether a declared code is REGISTERED and
# this one is. And it is unkeyable in `CODE_STATUS` BY CONSTRUCTION — nothing
# outside this fixture has ever heard of it, so no rung can add its line, and
# `_document_operation`'s `if status is not None` drops it forever. Registered,
# refusable, unpublished: the three facts the rule exists to notice, held by the
# plant itself.
from apps.core.exceptions import Forbidden, Remedy, register_refusal

register_refusal(
    code="canary_unpublished",
    boundary="door",
    remedy=(
        "Nothing. This code exists only inside house rule 47's canary fixture, which the "
        "gate plants into the tree and restores out of it; seeing it anywhere else means a "
        "self-test did not restore."
    ),
    fact=(
        "This operation refuses in a way the published document does not describe. The "
        "refusal is real and the contract is incomplete, which is the one thing a generated "
        "client cannot work around."
    ),
    remedies=(
        Remedy("Read the refusal registry for what this code means", "introspect:refusals"),
        Remedy("And the operation's own contract", "docs:openapi"),
    ),
)


class CanaryUnpublished(Forbidden):
    """Registered, refusable, and absent from `CODE_STATUS` by construction."""

    code = "canary_unpublished"
    default_detail = "This refusal is real and the document does not carry it."


@router.post("/canary-probe/", response={201: WidgetOut}, url_name="widget_canary_probe-create")
@refuses("canary_unpublished", "invalid", "rate_limited")
def canary_probe_write_route(request: TenantRequest, payload: WidgetIn) -> Any:
    """Create a probe widget

    Create a probe widget.

    Refusals you can get here:

    * `403 canary_unpublished` — the refusal this route exists to make, and the
      one the published document does not carry.
    * `400 invalid` — the body was malformed.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    raise CanaryUnpublished("the canary route is never called")
