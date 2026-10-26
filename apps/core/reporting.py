"""The exception reporter filter: Django's, widened to every credential name the tree speaks."""

from __future__ import annotations

import re

from django.views.debug import SafeExceptionReporterFilter


class CredentialReporterFilter(SafeExceptionReporterFilter):
    """Hides a setting or request variable whose name is Django's or ends `_PAT` or `_DSN`."""

    hidden_settings = re.compile(
        rf"{SafeExceptionReporterFilter.hidden_settings.pattern}|_PAT$|_DSN$",
        flags=re.IGNORECASE,
    )
