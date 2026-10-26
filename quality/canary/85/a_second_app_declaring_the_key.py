# Planted: a real app's own `surfaces.py`, declaring the key the probe app
# declares too — two apps, one surface key.
from apps.core.surfaces import ALL, Surface

SURFACES = {
    "zzz_twin": Surface(families=ALL, acts=ALL, roles=ALL, tenant_rule="addressed", screens=ALL),
}
