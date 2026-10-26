"""The role the customer surface admits — declared here, by the app that owns the surface.

`core.authz.role_declarations()` finds this file; nothing registers it. A role
belongs to ONE surface (`surfaces.py` names it), which is what makes
`core.surfaces.surface_for_role` a function: a customer's invitation, and every
other link built for them, lands on the customer host.

**What a customer holds, and why each pattern is there:**

* `widget.read` — they list and read the widgets they can see. Nothing else of
  the widget: no edit, no archive, no move. The surface offers those acts to
  nobody (`surfaces.py`), and this role could not press them anyway.
* `djb_tag.read`, `djb_tag_link.read` — the words on a widget are part of the
  record a customer reads: the widget's detail answers its tags, and without
  these the detail refuses on the tags while the list answers (both doors
  alike). They read the words; the `djb_tags` doors themselves stay off the
  customer surface.
* `portal_request.*` — their own noun, whole.
"""

from __future__ import annotations

# golden: portal begin
# golden: portal role begin
from pilecap import DeclaredRole

ROLES: dict[str, DeclaredRole] = {
    "customer": DeclaredRole(
        key="customer",
        name="Customer",
        permissions=("widget.read", "djb_tag.read", "djb_tag_link.read", "portal_request.*"),
        is_default_for_new_members=False,
        description="Reads the widgets they can see and sends requests about them.",
    ),
}
# golden: portal role end
# golden: portal end
