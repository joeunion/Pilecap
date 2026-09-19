"""Planted: a capability offered to a role nobody declares (clause b).

`DEFAULT_ROLES` is how an app hands its own capability to a role without the
role's author hearing about it — which only works if the role exists. `viewer`
is in no `roles.py` on this tree, so the offer reaches nobody and the app
believes it shipped a default it did not ship. `djb.W054` reports the same
shape at `--deploy`; this is the half that reads the code.
"""

DEFAULT_ROLES = {"gadget.create": frozenset({"viewer"})}
