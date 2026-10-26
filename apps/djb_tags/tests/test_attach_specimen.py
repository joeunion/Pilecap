"""The attach hook core's conformance tests import, proven here against the landing law."""

from __future__ import annotations

import pytest

from apps.core.models import Tenant
from apps.djb_tags.events import TAG_LINK_CREATED
from apps.djb_tags.services import create_tag
from apps.djb_tags.tests.attach_specimen import attach
from apps.djb_tags.tests.conftest import TagWorld
from apps.events.models import Event

pytestmark = pytest.mark.django_db


def _created(tenant: Tenant) -> int:
    return Event.objects.for_tenant(tenant).filter(name=TAG_LINK_CREATED).count()


@pytest.mark.usefixtures("widget_takes_tags", "tag_takes_tags")
def test_the_attach_specimen_lands_by_the_landing_law(world: TagWorld) -> None:
    """`attach` writes through the real service as the actor it is handed: on a
    branch-owned subject the link sits at the subject's branch; on a tenant-wide
    subject, at the acting hat. A second attach reuses the one specimen word."""
    on_widget = attach(tenant=world.tenant, actor=world.clerk, subject=world.widget_a)
    tenant_wide = create_tag(tenant=world.tenant, actor=world.owner, name="Region")
    on_word = attach(tenant=world.tenant, actor=world.clerk, subject=tenant_wide)
    assert on_widget.organization_id == world.widget_a.organization_id
    assert on_word.organization_id == world.a.pk
    assert on_widget.tag_id == on_word.tag_id
    assert _created(world.tenant) == 2
