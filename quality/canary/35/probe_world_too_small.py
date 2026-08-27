

# CANARY (rule 35, the world half — (b)): the sizing paragraph above,
# turned into something that can fail.
#
# `FILLER_ORGS = 400` is an argument written in prose: with only the three
# organizations the world used to have, reading all three and filtering is
# genuinely the cheaper plan, so the narrowing rule 35 pins was not the
# planner's own choice and could not honestly be asserted (P-1). Nothing
# checked that the argument still applied. This plant takes the world back to
# the measured RED edge — three fillers — and rule 35 must go red for it, both
# because the declaration loses the world that made it an assertion and,
# usually, because the plan itself stops narrowing on `path`.
#
# It rebinds the constant AND prunes the cached probe database down to it: the
# `_hp` database is reused between runs, so setting the number alone would
# change nothing at all — `ensure_world` only ever creates the fillers it is
# missing. The prune is safe and self-healing: the next ordinary run finds three
# and bulk-creates the same 397 rows back, under the same slugs and the same
# paths, because both are derived from the index.
FILLER_ORGS = 3  # planted violation

_canary_full_world = ensure_world


def ensure_world(world: World) -> None:  # noqa: F811
    from apps.core.models import Organization

    _canary_full_world(world)
    keep = [f"{FILLER_SLUG_PREFIX}{index:04d}" for index in range(FILLER_ORGS)]
    Organization.objects.filter(
        tenant=world.tenant, slug__startswith=FILLER_SLUG_PREFIX
    ).exclude(slug__in=keep).delete()
