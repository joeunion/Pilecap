

# CANARY (rule 59, class none_mapping): R4's F5 — a noun mapped to None while
# the app declares a model whose authorization kind IS that noun. `_may_read`
# answers True for a None kind whatever branch the frame names, so a real row's
# event declared org-less bypasses the read set for every connection in the
# tenant. The `ImproperlyConfigured` text itself offers this road.
EVENT_KINDS: dict[str, str | None] = {"widget": None}  # planted violation
