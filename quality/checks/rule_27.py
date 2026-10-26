"""Rule 27: one door to the identity platform."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 27: one door to the identity platform -------------------------------
#
# ADR ident-2. Identity configuration is written through our audited
# services and materialised in Zitadel by one activity; the console is a window,
# not a door. A check cannot see the console — that is the declared blind spot —
# but it can see the half that is in this tree, and this is that half, stated as
# a closed question with two shapes:
#
# 1. **the credential**: `ZITADEL_PAT` is named in `apps/accounts/zitadel.py`
# (where it is used) and in `config/settings/` (where the environment is
# read), and nowhere else. A third reader is a third place a PAT can reach a
# log line, an exception message or a subprocess environment.
# 2. **the client**: `apps.accounts.zitadel` is imported only from the places
# where a management call is legitimate — the activity, where a failure is a
# Temporal retry, and the `zitadel_*` commands that are the shell door. WHICH
# ones is `quality/rules.yaml`'s allow-list, and `python -m quality.gate
# --explain 27` prints it; no count is written here, because a count in a
# comment goes stale the run after a shell door is added. A module OFF that
# list may still import the client by carrying this rule's comment valve with
# its reason on the line — the reconcile command is the one that does, taking
# `configured()` and `ZitadelError` and writing nothing — so the reported
# `client_importers` is the allow-list PLUS every honoured valve, never the
# allow-list alone.
# A service importing it would put external I/O inside a transaction (C2); a
# route or a tool importing it would put an unbounded network call on
# somebody's request.
#
# Both halves are read from the AST rather than from the text, which is what
# makes the negatives possible: this module's own prose names `ZITADEL_PAT`
# repeatedly, and a check that fired on the word would fire on its own reasons.

# The setting whose only two homes are the client and the settings module.
PAT_SETTING = "ZITADEL_PAT"
# The module every other module must go through, and never around.
CLIENT_MODULE = "apps.accounts.zitadel"
CLIENT_PACKAGE, _, CLIENT_NAME = CLIENT_MODULE.rpartition(".")
ZITADEL_KLASS = "zitadel_client"


def _names_pat(node: ast.AST) -> bool:
    """Whether this node names the PAT setting. **Never prose.**

    Three shapes and exactly three: `settings.ZITADEL_PAT` (an attribute),
    `getattr(settings, "ZITADEL_PAT")` / `env.str("ZITADEL_PAT")` (a string
    constant that IS the name, not one that contains it), and a bare
    `ZITADEL_PAT` binding, which is how a settings module declares one. A
    docstring that mentions the variable is a `Constant` whose value is the
    whole docstring, so equality — rather than membership — is what keeps this
    silent on documentation.
    """
    if isinstance(node, ast.Attribute):
        return node.attr == PAT_SETTING
    if isinstance(node, ast.Name):
        return node.id == PAT_SETTING
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value == PAT_SETTING
    return False


def _imports_client(node: ast.AST) -> bool:
    """Whether this statement pulls in the management client. Import shapes only.

    The three a person writes: `from apps.accounts.zitadel import x`,
    `from apps.accounts import zitadel`, and `import apps.accounts.zitadel`.
    """
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module == CLIENT_MODULE or module.startswith(f"{CLIENT_MODULE}."):
            return True
        return module == CLIENT_PACKAGE and any(a.name == CLIENT_NAME for a in node.names)
    if isinstance(node, ast.Import):
        return any(
            a.name == CLIENT_MODULE or a.name.startswith(f"{CLIENT_MODULE}.") for a in node.names
        )
    return False


def zitadel_client(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    scope = rule.get("scope") or {}
    importers = [str(e.get("path", "")) for e in scope.get("allow_import") or [] if e.get("path")]
    readers = [str(e.get("path", "")) for e in scope.get("allow_secret") or [] if e.get("path")]
    client_rel = CLIENT_MODULE.replace(".", "/") + ".py"

    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        if rel == client_rel:
            # The module the rule funnels everything into. Its own PAT read and
            # its own client are the point, and they are counted so that a
            # recogniser that stopped recognising anything trips the floor
            # rather than reporting a clean nothing.
            out.count("client_module")
            for node in ast.walk(tree):
                if _names_pat(node):
                    out.count("pat_sites")
            continue

        may_import = any(rel == entry or rel.startswith(entry) for entry in importers)
        may_read = any(rel == entry or rel.startswith(entry) for entry in readers)

        for node in ast.walk(tree):
            if _names_pat(node):
                if may_read:
                    out.count("pat_sites")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"names the {PAT_SETTING} setting — the platform credential is read in "
                        f"{client_rel} and declared in config/settings, and nowhere else. Call "
                        f"{CLIENT_MODULE}, or add this module to rule 27's allow-list in "
                        "quality/rules.yaml with the reason. The two roads are not the "
                        "same size: the allow-list makes this MODULE a standing second "
                        "reader of the credential, where `# rule-27: <reason>` on this "
                        "line exempts this line and is counted and printed on every run",
                        klass=ZITADEL_KLASS,
                    )
                continue
            if not _imports_client(node):
                continue
            if may_import:
                out.count("client_importers")
                continue
            out.hit(
                rel,
                getattr(node, "lineno", 1),
                f"imports {CLIENT_MODULE} — the Zitadel management API is reached from an "
                "activity (where a failure is a retry) or a zitadel_* command, never from a "
                "service, a door or a selector: an external call inside a transaction is a "
                "hiccup that rolls back a legitimate row. Start "
                "SyncIdentityConfigWorkflow instead, or add this module to rule 27's "
                "allow-list in quality/rules.yaml with the reason — which makes this "
                "MODULE a standing importer, where `# rule-27: <reason>` on this import "
                "line exempts this line and is counted and printed on every run",
                klass=ZITADEL_KLASS,
            )
    return out
