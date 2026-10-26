"""The face's route table: where it lives and how a row and its `path` read.

The image carries no `quality/`, so this twin of rule 71's runner is pinned equal by test.
"""

from __future__ import annotations

import re

TABLE = "frontend/src/kit/routes.ts"
ROW = re.compile(r"\{[^{}]*\}")
PATH = re.compile(r"\bpath\s*:\s*([\"'`])([^\"'`\n]*)\1")
