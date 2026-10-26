"""Rule 45: every MCP dispatch surface is ceilinged."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 45: every MCP dispatch surface is ceilinged --------------------------
#
# . The server has three dispatch surfaces — `tools/call`, `resources/read`,
# `prompts/get` — each with its own manager, its own validation and its own path
# through the transport. Exactly one of them has a ceiling in front of it
# (`install_ceiling_gate`); the other two have a comment. Nothing is
# exposed today because this product registers no resources and no prompts, and
# that is precisely the moment to write the rule: rule 30's refusal in the other
# direction says a wall for a door nobody has is a schema built for a poller
# nobody wrote, so this rule refuses the FIRST registration on an unguarded
# surface and says nothing at all until then.


def _mcp_registration_sites(root: Path, names: set[str]) -> list[tuple[str, int, str]]:
    """`(relpath, line, attribute)` for every `<something>.<name>(...)` call under
    `apps/`/`config/`, for the registering attribute names a surface declares.

    DERIVED, because registration is by discovery: an app contributes a tool by
    exposing `register(server)` in its `mcp.py` and nothing here is edited when
    an app is added, so a list of modules would be the one thing the rest of the
    system refuses to keep. Test modules are outside the walk for rule 44's
    reason: a test that stands up its own server and registers a probe tool on
    it is how the door is proved at all.
    """
    sites: list[tuple[str, int, str]] = []
    for path in _py_files(root, "apps", "config"):
        rel = str(path.relative_to(root))
        if _is_test_module(rel):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in names:
                sites.append((rel, node.lineno, func.attr))
    return sites


def _marker_is_called(root: Path, marker: str) -> bool:
    """Whether anything under `apps/`/`config/` CALLS the named guard.

    A marker, not a proof: that the guard is correct is the mcp-wall tests' job
    and this rule says so out loud in `does_not_cover`. What it can see is the
    difference between a surface somebody put a wall in front of and a surface
    nobody did.
    """
    for path in _py_files(root, "apps", "config"):
        rel = str(path.relative_to(root))
        if _is_test_module(rel):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = _callee_name(func)
            if name == marker:
                return True
    return False


def mcp_dispatch_surfaces(root: Path, rule: dict) -> CheckResult:
    """Rule 45. Every dispatch surface the server has is censused, and ceilinged
    the moment anything is registered on it.

    Three clauses over one declared census:

      * every censused surface still exists on the INSTALLED SDK — its dispatch
        method and its manager attribute both — read off the package on disk;
      * every manager-shaped attribute the installed `MCPServer` binds is
        NAMED in the census, so a fourth surface cannot arrive unnoticed; and
      * a surface holding at least one registration whose declared guard marker
        is called nowhere is a violation, at every registration site.

    The first two are floors, which is to say exit 2: a census that cannot see
    cannot pass, and a green from a census that has gone blind is worse than no
    census at all.
    """
    out = CheckResult()
    entries = (rule.get("scope") or {}).get("mcp_dispatch_surfaces") or []
    classes = _mcp_class_attributes()
    managers = _mcp_server_manager_attributes()

    censused_managers: set[str] = set()
    for entry in entries:
        surface = str(entry.get("surface") or "?")
        dispatch = str(entry.get("dispatch") or "")
        manager = str(entry.get("manager") or "")
        guard = str(entry.get("guard") or "")
        registers = {str(name) for name in (entry.get("registers") or [])}
        censused_managers.add(manager)

        if classes is None or managers is None:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census names the `{surface}` surface and the installed `{_MCP_PACKAGE}` "
                "SDK could not be found on the import path at all, so nothing here is "
                "validating anything — the mount would discover it at startup",
                klass="census",
            )
            continue
        members = classes.get(_MCP_SERVER_CLASS, set())
        if dispatch not in members:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census says `{surface}` is dispatched by "
                f"`{_MCP_SERVER_CLASS}.{dispatch}` and the installed SDK no longer defines "
                f"`{dispatch}` — the wrap that holds it (or the wrap that would have to) is "
                "aimed at a seam that is not there. Follow the rename here first",
                klass="census",
            )
            continue
        if manager not in managers:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census says `{surface}` is served by `{_MCP_SERVER_CLASS}.{manager}` "
                f"and the installed SDK binds no such attribute (it binds "
                f"{', '.join(sorted(managers)) or 'none'}) — a census reading a manager that "
                "is gone cannot tell whether anything is registered on that surface",
                klass="census",
            )
            continue
        out.count("censused_surfaces", 1)

        guarded = bool(guard) and _marker_is_called(root, guard)
        if guarded:
            out.count("guarded_surfaces", 1)
        sites = _mcp_registration_sites(root, registers)
        # `tools/call` counts as `tools_registered` — the surface's own noun, so
        # the floor below reads as the fact it pins.
        out.count(f"{surface.split('/')[0]}_registered", len(sites))
        if not sites or guarded:
            continue
        for rel, line, attr in sites:
            out.hit(
                rel,
                line,
                f"`.{attr}(...)` registers on the `{surface}` dispatch surface and nothing "
                f"under apps/ or config/ calls `{guard}` — that surface reaches the "
                f"transport through `{_MCP_SERVER_CLASS}.{dispatch}` with no token-ceiling "
                "check in front of it, so a bearer whose ceiling reaches nothing here is "
                "answered about the request instead of refused (one surface "
                f"over). Install the guard from the registering app's `register()`, the way "
                "`install_ceiling_gate` is installed, and name it in this surface's census "
                "entry (quality/rules.yaml, rule 45). If this surface is guarded by "
                "something this detector cannot see, `# rule-45: <reason>` on this line is "
                "the counted, printed road — and it silences one line where the census "
                "entry teaches the next reader what guards this surface",
                root=root,
                klass="unguarded",
            )

    if managers is not None:
        unnamed = sorted(managers - censused_managers)
        if not unnamed:
            out.count("census_names_every_manager", 1)
        for attr in unnamed:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the installed `{_MCP_SERVER_CLASS}` binds `{attr}` and the census names no "
                "surface served by it — that is a dispatch surface this repository has never "
                "heard of, and a census that cannot see one cannot say the others are "
                "ceilinged. Add the entry (surface, dispatch, manager, registers, guard) in "
                "the commit that takes the SDK upgrade",
                klass="census",
            )
    return out


from quality.checks.rule_36 import _callee_name, _is_test_module  # noqa: E402
from quality.checks.rule_44 import (  # noqa: E402
    _CENSUS_DECLARATION,
    _MCP_PACKAGE,
    _MCP_SERVER_CLASS,
    _mcp_class_attributes,
    _mcp_server_manager_attributes,
)
