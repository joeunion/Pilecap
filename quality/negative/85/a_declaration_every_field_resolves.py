# Negative: a declaration in the worked customer surface's shape, every field
# resolving — families two apps' `TAGS` declare, the role core declares, the
# read act, the membership rule, and two screens the route table carries (the
# rows planted beside it), one with a `[id]` segment spelled as the table
# spells it.
from apps.core.surfaces import Surface

# Every form of this rule appends to the probe's one `surfaces.py`, so each
# adds its entry to the declaration rather than rebinding it.
SURFACES = globals().setdefault("SURFACES", {})
SURFACES["zzz_portal"] = Surface(
    families={"org-structure", "users"},
    acts={"read"},
    roles={"member"},
    tenant_rule="membership",
    screens={"/zzz-canary/portal", "/zzz-canary/portal/[id]"},
)
