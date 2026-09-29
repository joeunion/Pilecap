"""The import adoption's own test — copied with the adoption, and green on the copy.

Every line is fenced `golden: import`: the imports app discovers the noun's
importer by its kind, and its `apply` creates, leaves and edits through the
noun's own services — `created`, then `unchanged` for the same row, then
`updated` when the file says something new — keyed on `external_ref`.
"""

# golden: import begin
import pytest

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.example.models import Widget
from apps.imports.selectors import list_importers

pytestmark = pytest.mark.django_db


def test_the_importer_is_discovered_and_applies_through_the_nouns_services(
    tenant: Tenant, owner_actor: Actor
) -> None:
    importer = list_importers()["widget"]
    row = importer.row.model_validate({"external_ref": "CRM-1", "name": "w", "notes": "a"})

    made, first = importer.apply(tenant=tenant, actor=owner_actor, row=row)
    same, second = importer.apply(tenant=tenant, actor=owner_actor, row=row)
    edited = importer.row.model_validate({"external_ref": "CRM-1", "name": "w", "notes": "b"})
    changed, third = importer.apply(tenant=tenant, actor=owner_actor, row=edited)

    assert (first, second, third) == ("created", "unchanged", "updated")
    assert made.pk == same.pk == changed.pk
    assert importer.natural_key(tenant=tenant, actor=owner_actor, row=row).pk == made.pk
    assert Widget.objects.filter(tenant=tenant, external_ref="CRM-1").count() == 1


# golden: import end
