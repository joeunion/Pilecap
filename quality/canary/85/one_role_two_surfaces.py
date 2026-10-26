# Planted: one declared role admitted by two surfaces. A role belongs to one
# surface — which is what lets a link built for a person land on their host.
from apps.core.surfaces import ALL, Surface

# Every form of this rule appends to the probe's one `surfaces.py`, so each
# adds its entry to the declaration rather than rebinding it.
SURFACES = globals().setdefault("SURFACES", {})
SURFACES["zzz_left"] = Surface(
    families=ALL, acts=ALL, roles={"member"}, tenant_rule="membership", screens=ALL
)
SURFACES["zzz_right"] = Surface(
    families=ALL, acts=ALL, roles={"member"}, tenant_rule="membership", screens=ALL
)
