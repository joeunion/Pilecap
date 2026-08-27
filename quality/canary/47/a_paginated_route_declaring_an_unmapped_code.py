

# --- planted (house rule 47's second canary) -----------------------------------
#
# THE SAME DROP ON THE SHAPE MOST LIKELY TO HIDE IT, and it carries its own
# disease for the same reason its sibling does: it registers `canary_unpublished_list`
# and declares that. A SECOND code rather than the first one reused, because the
# two fixtures are planted separately and each has to stand alone — a canary that
# could only fire while another fixture was also in the tree is a canary with a
# dependency nobody declared.
#
# THE CLASS, RESTATED (corrected at the merge). Both of this rule's
# canaries first declared `session_required` — the live drop the rule was born
# against — and published that code in the same merge window and killed
# both at once. **An instrument may not depend on a patient staying ill.** A
# canary pointed at a real defect expires the day somebody fixes it, as exit 2,
# on their rung.
#
# WHY THIS SHAPE IS CANARIED SEPARATELY AT ALL. A paginated authenticated list
# route gets the cursor's two refusals from `@paginate` and a 401 written for it
# OUTSIDE the table walk, so `responses` is non-empty for reasons that have
# nothing to do with the declared set — which is exactly the arrangement a check
# asking "did anything get published at all" would read as a pass. It rescues
# nothing: the declared code is still keyed through `CODE_STATUS` and still
# dropped. Two canaries, because one that could only ever prove them together
# would prove neither.
from apps.core.exceptions import Forbidden as _CanaryForbidden
from apps.core.exceptions import Remedy as _CanaryRemedy
from apps.core.exceptions import register_refusal as _canary_register_refusal

_canary_register_refusal(
    code="canary_unpublished_list",
    boundary="door",
    remedy=(
        "Nothing. This code exists only inside house rule 47's paginated canary fixture, "
        "which the gate plants into the tree and restores out of it; seeing it anywhere "
        "else means a self-test did not restore."
    ),
    fact=(
        "This listing refuses in a way the published document does not describe. The "
        "cursor's own refusals ARE published, which is what makes the missing one easy to "
        "miss: the response object exists and is incomplete."
    ),
    remedies=(
        _CanaryRemedy("Read the refusal registry for what this code means", "introspect:refusals"),
        _CanaryRemedy("And the operation's own contract", "docs:openapi"),
    ),
)


class CanaryUnpublishedList(_CanaryForbidden):
    """Registered, refusable, and absent from `CODE_STATUS` by construction."""

    code = "canary_unpublished_list"
    default_detail = "This listing's refusal is real and the document does not carry it."


@router.get(
    "/canary-probes/", response=list[WidgetOut], url_name="widget_canary_probes-list"
)
@paginate(CursorPagination)
@refuses("canary_unpublished_list", "invalid_cursor", "not_found", "rate_limited")
def canary_probe_list_route(request: TenantRequest) -> Any:
    """List probe widgets

    List probe widgets.

    Refusals you can get here:

    * `403 canary_unpublished_list` — the refusal this listing exists to make,
      and the one the published document does not carry.
    * `400 invalid_cursor` — the `?cursor=` was built, edited or replayed.
    * `404 not_found` — the cursor names a walk this tenant cannot reach.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    raise CanaryUnpublishedList("the canary route is never called")
