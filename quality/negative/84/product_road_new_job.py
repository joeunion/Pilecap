# Planted: a product road for a job of the product's own. A new job with one
# road is growth, never a finding.
from apps.core.roads import road


@road("frobnicate", example="apps/zzz_canary/tests/test_frob.py::test_frobnicate")
def frobnicate() -> None:
    """The one way this product frobs."""
