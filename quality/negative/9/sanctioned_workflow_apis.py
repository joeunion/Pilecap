

# temporalio's own deterministic replacements. `workflow.now()`,
# `workflow.uuid4()`, `workflow.random()` and `workflow.time()` are the
# SANCTIONED way to do the banned thing: each is recorded in the run's history
# on first execution and replayed from it, so they answer identically for ever.
# A rule that banned them by method name would be telling authors to reach for
# the real clock instead, which is the defect it exists to prevent.
def _neg_sanctioned_apis() -> tuple:
    stamp = workflow.now()
    token = workflow.uuid4()
    ticks = workflow.time()
    # And the CHAINED forms, which are the correct way to write two of the
    # banned names: a method on a deterministic timestamp, and a draw from the
    # seeded generator temporalio hands out. A rule reading only the immediate
    # receiver would fire on both — code that did exactly the right thing, with
    # an override as its only exit.
    clock = workflow.now().time()
    roll = workflow.random().randint(1, 6)
    return stamp, token, ticks, clock, roll
