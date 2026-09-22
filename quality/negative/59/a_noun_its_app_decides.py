

# NEGATIVE (rule 59, class undecided_noun): the `usage.threshold.crossed`
# shape — a noun that is NOT an authorization kind, decided by the declaring
# app's own `EVENT_KINDS`. This is the form the class is pushing every
# undecided noun towards, so a rule that flagged it would refuse its own remedy.
EVENT_KINDS: dict[str, str | None] = {"gadget": "widget"}
GADGET_TUNED = "example.gadget.tuned"
