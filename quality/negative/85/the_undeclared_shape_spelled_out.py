# Negative: the undeclared shape, spelled out — the platform's staff surface
# declared total, exactly what a product that declares nothing gets.
from apps.core.surfaces import ALL, Surface

# Every form of this rule appends to the probe's one `surfaces.py`, so each
# adds its entry to the declaration rather than rebinding it.
SURFACES = globals().setdefault("SURFACES", {})
SURFACES["staff"] = Surface(families=ALL, acts=ALL, roles=ALL, tenant_rule="addressed", screens=ALL)
