"""The names of the things this app says happened. `<app>.<noun>.<past verb>`.

Published by `services.py` inside the write's transaction; the payload is
`ImportOut`, the shape the REST door answers with.
"""

from __future__ import annotations

#: A file was staged and its check started.
IMPORT_STAGED = "imports.import.staged"
#: The dry run finished: every row judged, nothing written to the noun.
IMPORT_PREVIEWED = "imports.import.previewed"
#: The apply finished: the clean rows written, the refused ones listed.
IMPORT_APPLIED = "imports.import.applied"
#: The run ended without applying — the file refused whole, a run that broke,
#: or a person cancelling it.
IMPORT_FAILED = "imports.import.failed"
