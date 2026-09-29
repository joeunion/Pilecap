"""The names of the things this app says happened. `<app>.<noun>.<past verb>`.

Published by `services.py` inside the write's transaction; the payload is
`ImportOut`, the shape the REST door answers with.
"""

from __future__ import annotations

#: A file was staged and its check started.
IMPORT_STAGED = "djb_imports.import.staged"
#: The dry run finished: every row judged, nothing written to the noun.
IMPORT_PREVIEWED = "djb_imports.import.previewed"
#: The apply finished: the clean rows written, the refused ones listed.
IMPORT_APPLIED = "djb_imports.import.applied"
#: The run ended without applying — the file refused whole, a run that broke,
#: or a person cancelling it.
IMPORT_FAILED = "djb_imports.import.failed"

#: The event grammar's noun is the short word; the model's authorization kind
#: carries the template's `djb_` prefix (so a product's own `Import` keeps the
#: kind its class name derives). This maps the one to the other, so a socket
#: can still ask who may hear each event.
EVENT_KINDS: dict[str, str | None] = {
    "import": "djb_import",
}
