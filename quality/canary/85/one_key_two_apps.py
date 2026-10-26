# Planted: the probe declares a surface key a second, real app declares too
# (`a_second_app_declaring_the_key.py`). One surface has one declaration.
from apps.core.surfaces import ALL, Surface

# Every form of this rule appends to the probe's one `surfaces.py`, so each
# adds its entry to the declaration rather than rebinding it.
SURFACES = globals().setdefault("SURFACES", {})
SURFACES["zzz_twin"] = Surface(
    families=ALL, acts=ALL, roles=ALL, tenant_rule="addressed", screens=ALL
)
