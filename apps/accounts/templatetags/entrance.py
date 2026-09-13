"""Presentation-only tags for the entrance chain. Reads settings; decides nothing.

Two tags, and neither of them is business logic:

* `brand_accent` — the one colour the entrance token block declares, VALIDATED,
  because the value is interpolated into a `<style>` element. A settings string
  is operator-controlled rather than attacker-controlled, so this is not a hole
  being closed; it is the difference between a typo that renders the wrong
  colour and a typo that silently ends the style rule and takes the rest of the
  block with it. Anything that is not a CSS hex colour falls back to the
  restrained neutral, so the page is always finished rather than half-styled.
* `product_name` — what this deployment calls itself, so the entrance chain and
  the hosted identity step read the SAME declared value instead of two.

There is deliberately no tag for the provider count. `{% get_providers %}` —
allauth's own — already answers it from the live population (the apps
`SOCIALACCOUNT_PROVIDERS` declares plus every `SocialApp` row on this site), and
a second counter here would be a second opinion about what the page is about to
render.
"""

from __future__ import annotations

import re

from django import template
from django.conf import settings

register = template.Library()

#: The restrained near-neutral of the neutral-bar ruling. A slate that reads as a
#: decision rather than as a default, and that no product will mistake for its
#: own brand — the recipe's `BRAND_ACCENT` step is the honest forcing point.
DEFAULT_ACCENT = "#3f4a5a"

#: `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`. A closed grammar rather than an
#: escape: a token that lands inside a declaration has to be a colour, and
#: "looks like a colour" is a thing a regex can actually decide.
HEX_COLOR = re.compile(r"\A#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z")


@register.simple_tag
def brand_accent() -> str:
    """The declared accent, or the restrained neutral when it is not a hex colour."""
    value = str(getattr(settings, "BRAND_ACCENT", "") or "").strip()
    return value if HEX_COLOR.match(value) else DEFAULT_ACCENT


@register.simple_tag
def product_name() -> str:
    """What this deployment calls itself."""
    return str(getattr(settings, "PRODUCT_NAME", "") or "").strip()
