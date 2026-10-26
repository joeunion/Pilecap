# Planted: a surface drawing a screen no row of the face's route table carries
# — a page the face never draws on that host.
from apps.core.surfaces import ALL, Surface

# Every form of this rule appends to the probe's one `surfaces.py`, so each
# adds its entry to the declaration rather than rebinding it.
SURFACES = globals().setdefault("SURFACES", {})
SURFACES["zzz_screen"] = Surface(
    families=ALL, acts=ALL, roles=ALL, tenant_rule="addressed", screens={"/zzz-canary/nowhere"}
)
