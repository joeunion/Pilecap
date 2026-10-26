"""What a workflow module imports: the finish seam, and nothing that reaches the database."""

from __future__ import annotations

from apps.core.determinism import run_to_finish

__all__ = ["run_to_finish"]
