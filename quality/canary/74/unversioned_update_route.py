

# Planted: the update route of the versioned card, with a body that has no
# `version` and an answer that carries none.

from apps.core.schemas import StrictIn as _StrictIn74e


class CanaryCardPatch(_StrictIn74e):
    """What a card's update takes — and it forgot the version."""

    title: str | None = None


@router.patch("/cards/{card_id}/", response=CanaryCardPatch, url_name="canary_card-update")
def canary_card_update(request, card_id: str, payload: CanaryCardPatch):
    """Update a card

    Change one card's title.
    """
    return payload
