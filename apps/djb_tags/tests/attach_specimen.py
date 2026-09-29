"""The attach hook core's conformance tests import: put one tag on a subject.

`attach(*, tenant, actor, subject)` attaches THIS app's row to `subject` through
the service that really writes it, as `actor`, and answers the row — so the
repointer and landing-law conformance tests can plant an attachment on any
noun without knowing how tags are made. The subject's model must already take
tags (`attachments` lists `"tags"`); the caller declares that, not this hook.

The word is coined at the tenant's root by the product acting for itself,
because coining is a root write (house rule 55) that the attaching actor —
often a branch member — may not hold; the LINK is written as `actor`, which is
the write under test. One word per tenant, reused on every call.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor, system_actor
from apps.core.authz import kind_of
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.djb_tags.models import Tag, TagLink
from apps.djb_tags.services import create_tag, create_tag_link

#: The word every specimen attachment carries.
SPECIMEN_WORD = "Specimen"


def attach(*, tenant: Tenant, actor: Actor, subject: Any) -> TagLink:
    """Put the specimen word on `subject` as `actor`; answer the link."""
    word = Tag.objects.for_tenant(tenant).including_archived().filter(slug="specimen").first()
    if word is None:
        coiner = system_actor(tenant=tenant, org=root_organization(tenant=tenant))
        word = create_tag(tenant=tenant, actor=coiner, name=SPECIMEN_WORD)
    pointer = f"{kind_of(type(subject))}:{subject.pk}"
    return create_tag_link(tenant=tenant, actor=actor, tag=word, subject=pointer).link
