

# Planted: a hand-built archive half — an `archived_at` column on a class that
# never declared `Archivable`, so the book hides nothing and no road is owed.

from django.db import models as _models74l

from apps.core.models import OrgScopedModel as _OrgScoped74l


class CanaryShelfBare(_OrgScoped74l):
    archived_at = _models74l.DateTimeField(null=True, blank=True)
