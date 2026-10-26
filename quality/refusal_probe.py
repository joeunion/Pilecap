"""Rule 47's runner: what every bound operation DECLARES, against what the document SAYS.

Started as a subprocess by `quality/checks/rule_47.py::declared_refusals_documented` —
never by the default suite. It is a subprocess for the reason
`quality/hotpath_probe.py` is one and for the reason rule 44 reads ninja off the
disk rather than importing it: the gate must not stand Django up in its own
process. `document_api()` runs at import of `config/api.py` and every rule's
canary would die together on the day that import fails, which is the malady rule
44's docstring records having lived through once.

THE FACT IT MEASURES. A route says what it can refuse with, either by declaring
it (`@refuses(...)`) or by the shape derivation (`docs.derived_refusals`), and
`config/api.py::_document_operation` turns that set into responses keyed by
status — through `CODE_STATUS.get(code)`, `if status is not None`. A code with no
line in that table is dropped from the document IN SILENCE: the route still
refuses that way on the wire, and the published `x-refusal-codes` a generated
client switches on has no branch for it. found the live instance.

Output: one JSON object on stdout —
    {"operations": N, "registry_codes": R, "registry": [code, ...],
     "documented_codes": D, "narrowed_routes": W,
     "drops": [{"path": ..., "line": ..., "route": ..., "operation_id": ...,
                "code": ..., "in_code_status": bool, "status": int|null,
                "declared": bool}, ...]}
Exit 0 whether or not there are drops (the check turns drops into findings); a
non-zero exit means the probe itself could not run, which the check surfaces as
a finding AND an unbound floor — enforcement broken, never a pass.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _where_it_is_written(view: Any) -> tuple[str, int]:
    """The route's OWN file and line, past whatever decorated it.

    `@paginate` returns a `functools.wraps`-ed wrapper defined in ninja's own
    `pagination.py`, so `view.__code__` on a paginated route points into
    site-packages — a finding pathed there names a file nobody in this tree can
    fix. The `__wrapped__` chain is walked to the first frame that is actually in
    this tree, which is the function somebody wrote.
    """
    candidate = view
    seen = 0
    while candidate is not None and seen < 10:
        code = getattr(candidate, "__code__", None)
        if code is not None:
            try:
                rel = Path(code.co_filename).relative_to(ROOT)
            except ValueError:
                rel = None
            if rel is not None and ".venv" not in rel.parts:
                return str(rel), int(code.co_firstlineno)
        candidate = getattr(candidate, "__wrapped__", None)
        seen += 1
    return "config/api.py", 0


#: A contract's refusal bullet: `* `<status> <code>`` — the code a caller is told to handle.
_REFUSAL_BULLET = re.compile(r"^\s*[*-]\s+`\d{3}\s+([a-z][a-z0-9_]*)`", re.MULTILINE)


def _bulleted_codes(view: Any) -> set[str]:
    """The codes the route's docstring bullets name, above the contract divider."""
    doc = inspect.getdoc(view) or ""
    return set(_REFUSAL_BULLET.findall(doc.split("\n---\n", 1)[0]))


def main() -> int:
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    import django

    django.setup()

    # THE REGISTRY IS POPULATED AT IMPORT, so the probe imports BOTH doors: the
    # MCP door (`apps.core.mcp`) registers the machine-door code
    # (`invalid_arguments`) the REST mount never imports, and a registry read
    # from one door is one code short of the one rule 41 reads off the tree.
    from apps.accounts.auth import Unauthenticated
    from apps.core import mcp as _machine_door  # noqa: F401
    from apps.core.api import docs
    from config import api as mount

    operations = 0
    narrowed = 0
    documented_codes: set[str] = set()
    drops: list[dict[str, Any]] = []
    unpublished: list[dict[str, Any]] = []

    for bound in mount.api._get_bound_routers():
        for path, path_view in bound.path_operations.items():
            segments = [part.strip("/") for part in (bound.prefix, path) if part.strip("/")]
            full = "/" + "/".join(segments)
            for operation in path_view.operations:
                operations += 1
                view = operation.view_func
                authenticated = bool(operation.auth_callbacks)
                declared = docs.declared_refusals(view)
                if declared is not None:
                    narrowed += 1
                    codes = tuple(declared)
                else:
                    codes = docs.derived_refusals(
                        methods=operation.methods,
                        has_path_params="{" in full,
                        has_body=mount._has_body(operation),
                        authenticated=authenticated,
                        idempotent_methods=mount.IDEMPOTENT_METHODS,
                        paginated=bool(getattr(view, "_ninja_is_paginated", False)),
                    )
                # `@also_refuses` adds to either branch, as `config/api.py` does.
                codes = docs.with_added(codes, view)
                owed = set(codes)
                if authenticated:
                    # The one response `_document_operation` adds outside the
                    # table walk, read the same way it writes it.
                    owed.add(Unauthenticated.code)

                published: set[str] = set()
                for response in (operation.openapi_extra or {}).get("responses", {}).values():
                    if isinstance(response, dict):
                        published |= set(response.get("x-refusal-codes") or ())
                documented_codes |= published
                rel, line = _where_it_is_written(view)
                for code in sorted(_bulleted_codes(view) - published):
                    unpublished.append(
                        {
                            "path": rel,
                            "line": line,
                            "route": getattr(view, "__name__", "?"),
                            "operation_id": f"{sorted(operation.methods)[0]} {full}",
                            "code": code,
                        }
                    )

                for code in sorted(owed - published):
                    status = mount.CODE_STATUS.get(code)
                    rel, line = _where_it_is_written(view)
                    drops.append(
                        {
                            "path": rel,
                            "line": line,
                            "route": getattr(view, "__name__", "?"),
                            "operation_id": f"{sorted(operation.methods)[0]} {full}",
                            "code": code,
                            "in_code_status": status is not None,
                            "status": status,
                            "declared": declared is not None,
                        }
                    )

    json.dump(
        {
            "operations": operations,
            "registry_codes": len(docs.REFUSALS),
            "registry": sorted(docs.REFUSALS),
            "documented_codes": len(documented_codes),
            "narrowed_routes": narrowed,
            "drops": drops,
            "unpublished_bullets": unpublished,
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
