"""Planted: a declared key naming a kind no model derives (clause a).

`gizmo` is not a first-party model here and it is not one of the virtual kinds,
so `gizmo.polish` is a capability over nothing. Nobody can ever be given it in
a way that means anything, and `require` cannot say so — it resolves the key,
finds no policy and falls through to the role.
"""

ACTION_PROSE = {"gizmo.polish": "You may not polish this gizmo."}
