

# The seam's content read where it belongs: an activity's parser, reading a file
# row by row inside the worker — the import app's shape.
from apps.files import storage as _files_storage48


def _negative_parses_rows(tenant, key):  # noqa: ANN001, ANN202
    return [len(chunk) for chunk in _files_storage48.iter_object(tenant=tenant, key=key)]
