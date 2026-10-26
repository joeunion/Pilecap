# Planted: the deployment binds a host to a surface no app declares. The
# binding is environment, so the form sets it the way the settings would.
from django.conf import settings

settings.SURFACE_HOSTS = {
    **(getattr(settings, "SURFACE_HOSTS", None) or {}),
    "zzz_nowhere": "zzz-nowhere.localhost",
}
