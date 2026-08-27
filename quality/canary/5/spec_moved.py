

# CANARY (rule 5, the stamp seam): the fixture contract grows one axis.
#
# This is F1d's move, replayed: a `ScaleSpec` edit lands, every seeded world
# from then on is a different world, and the four measurement docs go on
# carrying the hash of the world they were written against. Nothing in the tree
# said so until this check existed — the seeder compares its stamp against the
# DATABASE and re-seeds, and nobody compared it against the prose.
#
# Redefined as a subclass rather than a re-typed copy of the dataclass: the
# whole point is that ONE new field is enough, and a copy would have to be kept
# in step with the real one to keep proving it.
@dataclasses.dataclass(frozen=True)
class _CanaryScaleSpec(ScaleSpec):  # noqa: F811  # planted violation
    canary_axis: int = 1


ScaleSpec = _CanaryScaleSpec  # noqa: F811  # planted violation
