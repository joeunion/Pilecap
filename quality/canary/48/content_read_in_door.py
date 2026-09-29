

# Planted: the seam's own content read called from a door — a stored document's
# bytes streamed through Django to a caller.
from apps.files.storage import iter_object as _iter_object48


def _canary_streams_a_document(tenant, key):  # noqa: ANN001, ANN202
    return b"".join(_iter_object48(tenant=tenant, key=key))
