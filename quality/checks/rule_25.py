"""Rule 25: only comms sends."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 25: only comms sends ------------------------------------------------
#
# The closed question: does any module under apps/ outside the allow-list import
# a module that CARRIES A MESSAGE OUT OF THIS PRODUCT? `comms.send()` is the only
# legal sender — consent, quiet hours and suppression are enforced INSIDE it, so
# a feature that reaches for one of these reaches around all three. The rule is
# mechanical because the alternative is remembering.
#
# THE POPULATION IS DATA. It was two hard-coded mail modules
# while email was the only transport; ADR comms-9 grows the product to three
# (`twilio` now, `firebase_admin` at T3), and the ADR's own sentence is that the
# wall "covers three transports, same rule id". So the senders are declared in
# `rules.yaml` beside the allow-list they are allowed at, one entry with its
# reason, and adding the next transport is a yaml line and a canary rather than
# an edit here. The two mail modules stay the default when a rule declares no
# senders at all, so the check still answers for a rule file that predates this.
_DEFAULT_SENDERS = ("django.core.mail", "apps.core.mail")
MAIL_KLASS = "mail_imports"


def _senders(rule: dict) -> tuple[str, ...]:
    """The sender modules this rule forbids, declared in `scope.senders`."""
    declared = [
        str(entry.get("module", "")).strip()
        for entry in (rule.get("scope") or {}).get("senders") or []
        if str(entry.get("module", "")).strip()
    ]
    return tuple(declared) or _DEFAULT_SENDERS


def _sender_packages(senders: tuple[str, ...]) -> dict[str, str]:
    """`{"apps.core": "apps.core.mail"}` — derived, so a declaration is enough.

    It is the `from apps.core import mail` shape and it needs the parent package
    and the leaf name, which a dotted sender already carries. A sender that is a
    whole top-level package (`twilio`) has no such shape to derive: `from twilio
    import rest` is caught by the name itself, one branch up.
    """
    out: dict[str, str] = {}
    for module in senders:
        package, _, leaf = module.rpartition(".")
        if package:
            out[f"{package}:{leaf}"] = module
    return out


def _mail_import(node: ast.AST, senders: tuple[str, ...]) -> str | None:
    """The sender module this statement pulls in, or None. Import shapes only.

    Three forms reach a sender and they are the three a person writes:
    `from django.core.mail import send_mail`, `from apps.core import mail`, and
    `import django.core.mail` — and, for a sender that is a package rather than
    a module, `from twilio.rest import Client` and `import twilio`, which the
    same two branches already cover. Prose that merely NAMES one — every
    docstring in `apps/comms` does — is not an import and is not a finding; that
    restraint is what the negatives here are for.
    """
    packages = _sender_packages(senders)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module in senders or any(module.startswith(f"{m}.") for m in senders):
            return module
        for alias in node.names:
            named = packages.get(f"{module}:{alias.name}")
            if named:
                return named
        return None
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name in senders or any(alias.name.startswith(f"{m}.") for m in senders):
                return alias.name
    return None


def _permitted_senders(rel: str, rule: dict, senders: tuple[str, ...]) -> set[str]:
    """Which senders this file may import, unioned over every allow entry it matches.

    An entry with no `modules` list permits every sender at that path, which is
    what the mail-only allow-list has always meant. An entry WITH one is a
    pinned exemption — ADR comms-9 asks for exactly one, `twilio` at
    `apps/comms/providers.py` — and pinning is the difference between "the comms
    app may carry messages" and "any file in the comms app may reach for a
    vendor's SDK".
    """
    permitted: set[str] = set()
    for entry in (rule.get("scope") or {}).get("allow") or []:
        path = str(entry.get("path", ""))
        if not path or not (rel == path or rel.startswith(path)):
            continue
        modules = [str(name).strip() for name in entry.get("modules") or [] if str(name).strip()]
        permitted |= set(modules) if modules else set(senders)
    return permitted


def mail_imports(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    senders = _senders(rule)
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        permitted = _permitted_senders(rel, rule, senders)
        for node in ast.walk(tree):
            module = _mail_import(node, senders)
            if module is None:
                continue
            if any(module == name or module.startswith(f"{name}.") for name in permitted):
                # The allow-list's own matches are counted, and the count is
                # floored: if the recogniser above ever stopped recognising an
                # import, THESE would go quiet first and the floor would say so
                # — where the violation count going to zero would read as a pass.
                out.count("allowed_mail_modules")
                continue
            out.hit(
                rel,
                getattr(node, "lineno", 1),
                f"imports {module} — comms.send() is the only legal sender in this product, "
                "and consent, quiet hours and suppression are enforced inside it. Call it, or "
                "add this module to rule 25's allow-list in quality/rules.yaml with the "
                "reason — and note which road that is: the allow-list exempts the MODULE "
                "for every line it will ever hold, where `# rule-25: <reason>` on this "
                "import line exempts this import and is counted and printed on every run",
                klass=MAIL_KLASS,
            )
    return out
