"""Who may submit a portal request. **Policies are code; roles are DATA.**

There is no predicate here, and that is the lesson: submitting a request is a
capability a ROLE holds (`roles.py` gives the `customer` role
`portal_request.*`; `admin` holds it through `("*",)` and `owner` through the
vocabulary), so the vocabulary needs only the sentence a refused caller reads.
Which widget a person may ask about is not a policy either — it is reach,
asked by `core.authz.may_be_named` in the service before anything else.
"""

from __future__ import annotations

# golden: portal begin
ACTION_PROSE: dict[str, str] = {
    "portal_request.submit": "You may not send requests about widgets here.",
}
# golden: portal end
