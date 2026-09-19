"""Planted: a declared verb that is another spelling of `read` (clause a).

`gadget.view` is the shape the census exists to find. The kind derives four
verbs already — create, read, update, delete — and `view` is a second word for
one of them, so a deployment ends up with two keys for one capability and a
role that names one of them silently misses the other. The remedy is a rename
in the app's own `RENAMED_PERMISSIONS`, which keeps the old word answering
while the vocabulary becomes one shape.
"""

ACTION_PROSE = {"gadget.view": "You may not view this gadget."}
