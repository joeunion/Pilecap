# Planted: a surface offering an act that is no verb of the permission
# vocabulary and no family road — a button no face will ever be offered.
from apps.core.surfaces import ALL, Surface

# Every form of this rule appends to the probe's one `surfaces.py`, so each
# adds its entry to the declaration rather than rebinding it.
SURFACES = globals().setdefault("SURFACES", {})
SURFACES["zzz_act"] = Surface(
    families=ALL, acts={"zzz_polish"}, roles=ALL, tenant_rule="addressed", screens=ALL
)
