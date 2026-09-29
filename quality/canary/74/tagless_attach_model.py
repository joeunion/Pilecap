

# Planted: a noun that takes tags and whose record never answers them — the
# words are on the row and no read can say which.

from django.db import models as _models74k

from apps.core.models import OrgScopedModel as _OrgScoped74k


class CanaryTote(_OrgScoped74k):
    attachments = ("tags",)
    label = _models74k.CharField(max_length=32)
