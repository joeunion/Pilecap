# Planted: a surface exposing a scope family no app's `TAGS` declares. The
# declaration is accepted as written and the host answers nothing under it.
from apps.core.surfaces import ALL, Surface

# Every form of this rule appends to the probe's one `surfaces.py`, so each
# adds its entry to the declaration rather than rebinding it.
SURFACES = globals().setdefault("SURFACES", {})
SURFACES["zzz_family"] = Surface(
    families={"zzz_frobnicate"}, acts=ALL, roles=ALL, tenant_rule="addressed", screens=ALL
)
