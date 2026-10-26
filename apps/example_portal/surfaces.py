"""The customer surface: what the customer host exposes — declared by the app that owns it.

`core.surfaces.declared()` finds this file through the one discovery walk;
nothing registers it. Which host answers as `customer` is environment
(`SURFACE_HOSTS=staff=sales.example.com,customer=customer.example.com`), so a
staging host moves without a line of code; what the host OFFERS is this
declaration, and each field is a closed question over the tree:

* `families` — the scope families the customer host's doors answer: the
  widgets they read and their own requests. Every other family — notes, tags,
  the org tree, tokens — answers `surface_does_not_expose` here, exactly as an
  operation that does not exist.
* `acts` — the family acts a face is OFFERED here: `read`, and no verb. The
  customer role could not press an archive anyway; this is what keeps the face
  from drawing the button.
* `roles` — the role this surface admits, `customer` (`roles.py`). A membership
  with any other role resolves no tenant here.
* `tenant_rule` — `membership`: the customer's one membership among the
  admitted roles chooses the workspace. No header, no host pattern.
* `screens` — the face's pages this surface draws, the route table's paths
  (`frontend/src/kit/routes.ts`, whose rows for them carry
  `surfaces: ["customer"]`). The face reads its table; this answer is the
  server's, for machines. `tests/test_surface.py` holds the two to one set.
"""

from __future__ import annotations

# golden: portal begin
# golden: portal surface begin
from pilecap.surfaces import Surface

SURFACES: dict[str, Surface] = {
    "customer": Surface(
        families={"widgets", "portal_requests"},
        acts={"read"},
        roles={"customer"},
        tenant_rule="membership",
        screens={"/requests", "/requests/[id]", "/widgets", "/widgets/[id]"},
    ),
}
# golden: portal surface end
# golden: portal end
