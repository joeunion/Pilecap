

# NEGATIVE (rule 59, class undecided_noun): the `search.engine.degraded` shape —
# a noun decided as `None` with the reason beside it, because no row is behind
# it. `None` is a DECIDED answer and the class must not read it as a missing
# one; the case where a None IS wrong is class `none_mapping`'s, and it needs a
# model of that name, which `apps/example` does not declare for this noun.
EVENT_KINDS: dict[str, str | None] = {
    # A deployment-wide fact, not a row: nobody could hold a read on it.
    "telemetry": None,
}
TELEMETRY_SAMPLED = "example.telemetry.sampled"
