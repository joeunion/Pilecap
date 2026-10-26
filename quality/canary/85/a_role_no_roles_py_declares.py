# Planted: a surface admitting a role no app's `roles.py` declares — a
# membership can never carry it, so the surface admits nobody by that name.
from apps.core.surfaces import ALL, Surface

# Every form of this rule appends to the probe's one `surfaces.py`, so each
# adds its entry to the declaration rather than rebinding it.
SURFACES = globals().setdefault("SURFACES", {})
SURFACES["zzz_role"] = Surface(
    families=ALL, acts=ALL, roles={"zzz_nobody"}, tenant_rule="membership", screens=ALL
)
