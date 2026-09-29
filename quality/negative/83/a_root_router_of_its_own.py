"""Negative: a router at the root prefix, beside the seven live ones, on a word of its own.

Seven routers share the mount prefix "" and answer side by side, which is why
the rule reads PATHS and never prefixes: a guard on the prefix would refuse the
tree itself. Planted as the probe's api.py BASE with `mode: default` — when the
whole corpus runs, another rule's form has already created the probe's api.py
and this file is not written; when this rule runs alone, it is the probe's
router, mounted at the root under a path and a tag nobody else serves, and the
check must stay silent.
"""

from ninja import Router

from apps.core.api.docs import Tag

TAGS = {
    "zzz-canary": Tag(
        "Gate probe",
        "The quality gate's probe app. Nothing here is a product capability: these "
        "routes exist for the length of one self-test run, so a planted violation "
        "can be shown to fire through the real registries.",
    ),
}

router = Router(tags=["zzz-canary"])

PREFIX = ""


@router.get("/zzz-canary-things/{thing_id}/", url_name="zzz_canary_thing-detail")
def zzz_canary_thing_detail(request, thing_id: str):
    """Retrieve a thing

    One thing by id, from the part of the tenant this hat covers.

    A thing in a sibling branch answers `not_found`, exactly as one in another
    tenant does.
    """
    return {"id": thing_id}
