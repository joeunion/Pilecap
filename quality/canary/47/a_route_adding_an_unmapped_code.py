# --- planted (house rule 47's third canary) -------------------------------------
#
# THE SAME DROP THROUGH THE ADDITIVE DECORATOR. `@also_refuses(...)` adds a code
# to the set a route publishes anyway; the probe must read it exactly as
# `config/api.py` composes it, or rule 47 would stop seeing a drop the moment a
# product wrote the new decorator instead of `@refuses`. Its OWN code, for the
# second canary's reason: the fixtures are planted separately.
from apps.core.api.docs import also_refuses as _also_refuses47
from apps.core.exceptions import Forbidden as _Forbidden47
from apps.core.exceptions import Remedy as _Remedy47
from apps.core.exceptions import register_refusal as _register_refusal47

_register_refusal47(
    code="canary_unpublished_added",
    boundary="door",
    remedy=(
        "Nothing. This code exists only inside house rule 47's third canary fixture, which "
        "the gate plants into the tree and restores out of it."
    ),
    fact=(
        "This operation refuses in a way the published document does not describe, added "
        "through `@also_refuses`."
    ),
    remedies=(_Remedy47("Read the refusal registry for what this code means", "introspect:refusals"),),
)


class CanaryUnpublishedAdded(_Forbidden47):
    """Registered, refusable, added by `@also_refuses`, and absent from `CODE_STATUS`."""

    code = "canary_unpublished_added"
    default_detail = "This refusal is real and the document does not carry it."


@router.post("/canary-added/", response={201: WidgetOut}, url_name="widget_canary_added-create")
@_also_refuses47("canary_unpublished_added")
def canary_probe_added_route(request: TenantRequest, payload: WidgetIn) -> Any:
    """Create an added-probe widget

    Create an added-probe widget.
    """
    raise CanaryUnpublishedAdded("the canary route is never called")
