"""Rule 43: one outbound signer, and the scheme census."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 43: one outbound signer, and the scheme census ----------------------
#
# Rule 40's `does_not_cover` carried the trigger in prose — "OUTBOUND
# header dictionaries ... a later rung may unify them (trigger: the second
# outbound signer)" — and landed a second SCHEME through the one signer,
# which is the moment that trigger stops being hypothetical. Two failures, and
# both are silent:
#
# 1. A SECOND SIGNER. A module that computes an HMAC over an outbound body and
# puts it in a header is a second implementation of the one thing every
# subscriber's code is written against. It breaks nothing on the day it
# lands; it breaks later, when the two disagree about a prefix, an encoding
# or a timestamp, inside somebody else's integration.
# 2. A SCHEME DROPPED IN FEWER THAN ALL ITS SITES. A scheme lives in three
# places at once — the header the delivery writes, the reference receiver a
# subscriber copies, and the prose the contract publishes. Drop it in one
# and the tree is green while a stranger's verifier stops matching, or
# while the document promises a header nothing sends.
#
# THE CONTRACTION IS THE DESIGN CONSTRAINT, not an afterthought. `X-Signature`
# is recorded-not-taken: it goes when the first product's subscribers have
# migrated, and the day it goes must be ONE green commit. So every number here
# survives it — `signature_schemes` floors at 1 and is never hardwired to 2 —
# and the populations are the three sites the recorded contraction actually
# edits.
#
# WHY THE VERIFIER MODULE IS NOT ONE OF THE THREE. `apps/events/receivers.py`
# keeps `signature_matches` after the contraction, because that bare-HMAC shape
# also verifies INBOUND PROVIDER deliveries, whose schemes are theirs . A
# three-way equality that included the verifier module would refuse the
# contraction it was built to allow. What the verifier owes instead is the other
# direction, as a subset: every VERSIONED house seam it grows must be a scheme
# the delivery actually sends — a parser for a header nobody sends is a branch
# nothing can reach, and the shape a reviewer reads as support.

# : `X-Signature`, `X-Signature-V2`, and whatever a later scheme is called.
_SIGNATURE_NAME_RE = re.compile(r"X-Signature[A-Za-z0-9-]*", re.IGNORECASE)

# : The house verifier's seam grammar: `signature_v2_matches`, `parse_signature_v2`.
# : A bare `signature_matches` is v1 and is the declared dual-role shape.
_VERIFIER_SEAM_RE = re.compile(r"^(?:parse_)?signature_v(\d+)(?:_matches)?$")

# : Where the contract divider is defined. Read, never re-typed (rule 41's own).
_CONTRACT_DIVIDER_SOURCE = "apps/core/api/docs.py"


def _as_header_string(
    node: ast.expr, *, root: Path, here_constants: dict[str, str], modules: dict[str, str]
) -> str | None:
    """The string an expression names, when it is one this walk can resolve.

    Three forms and no more, for the same reason rule 40's read resolution stops
    where it does: a literal, a constant in this module, and a constant reached
    through a module this module imported. A name built at runtime is somebody
    else's control flow.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return here_constants.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        dotted = modules.get(node.value.id)
        if not dotted:
            return None
        target = root.joinpath(*dotted.split("."))
        for candidate in (target.with_suffix(".py"), target / "__init__.py"):
            if candidate.is_file():
                return _module_string_constants(_parse(candidate)).get(node.attr)
    return None


def _signature_names(root: Path, path: Path, *, kinds: set[str]) -> set[str]:
    """Every `X-Signature*` name this module NAMES IN CODE, by expression kind.

    `dict` is a key in a dict literal or a subscript assignment — the shape a
    header is written in. `call` is an argument or a subscript slice — the shape
    a header is read in. Never a docstring or a comment: prose is population B's
    third site, and reading it here would let a paragraph stand in for a header.
    """
    tree = _parse(path)
    if tree is None:
        return set()
    here = _module_string_constants(_parse(path))
    modules, _symbols = _import_maps(root, tree, _dotted(root, path))
    candidates: list[ast.expr] = []
    for node in ast.walk(tree):
        if "dict" in kinds:
            if isinstance(node, ast.Dict):
                candidates.extend(key for key in node.keys if key is not None)
            elif isinstance(node, ast.Assign):
                candidates.extend(
                    target.slice for target in node.targets if isinstance(target, ast.Subscript)
                )
        if "call" in kinds:
            if isinstance(node, ast.Call):
                candidates.extend(node.args)
                candidates.extend(keyword.value for keyword in node.keywords)
            elif isinstance(node, ast.Subscript):
                candidates.append(node.slice)
    found: set[str] = set()
    for candidate in candidates:
        value = _as_header_string(candidate, root=root, here_constants=here, modules=modules)
        if value and _SIGNATURE_NAME_RE.fullmatch(value):
            found.add(value)
    return found


def _hmac_shape(tree: ast.Module) -> tuple[bool, bool]:
    """(computes an HMAC, compares one). The discriminator between the two jobs.

    A VERIFIER computes a digest and hands it to `hmac.compare_digest`; a SIGNER
    computes one and sends it. Derived rather than listed, so a product's own
    inbound verifier is outside this rule the day it is written and never needs
    an exemption — and so that a module which stops comparing and starts sending
    is in the population from that commit.
    """
    computes = compares = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        owner = (_callee_name(func.value) or "") if isinstance(func.value, ast.Name) else ""
        if owner == "hmac" and func.attr in ("new", "digest"):
            computes = True
        if func.attr == "compare_digest":
            compares = True
    return computes, compares


def _contract_docstring(root: Path, rel: str, function: str) -> str:
    """The contract half of one route's docstring, read the way `docs.py` reads it.

    The divider is read OFF `apps/core/api/docs.py` rather than typed here: the
    convention belongs to the module that publishes it, and a rule carrying its
    own copy would be the second spelling this engine exists to refuse.
    """
    divider = _module_string_constants(_parse(root / _CONTRACT_DIVIDER_SOURCE)).get(
        "CONTRACT_DIVIDER", "---"
    )
    tree = _parse(root / rel)
    if tree is None:
        return ""
    # The LAST definition wins, because that is what Python does: a module that
    # defines a name twice answers with the second one. It is also what makes an
    # append a legal plant site — a canary that redefines the route is the tree
    # this module would really import.
    doc = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            doc = ast.get_docstring(node) or ""
    lines = doc.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == divider:
            return "\n".join(lines[:index])
    return doc


def outbound_signer_census(root: Path, rule: dict) -> CheckResult:
    """Rule 43. One signer, and a scheme is sent, verifiable and documented.

    Every site is DECLARED in `rules.yaml` with the reason it is that site,
    because "which module signs" is a judgement and not a discovery. What is
    derived is everything else: who ELSE signs, and which schemes each site
    names.
    """
    out = CheckResult()
    scope = rule.get("scope") or {}
    signer_rel = str((scope.get("declared_signer") or {}).get("module", ""))
    verifier_rel = str((scope.get("declared_verifier") or {}).get("module", ""))
    receiver_rel = str((scope.get("reference_receiver") or {}).get("module", ""))
    contract = scope.get("contract_prose") or {}
    contract_rel = str(contract.get("module", ""))
    contract_fn = str(contract.get("function", ""))

    # --- population A: who signs ---------------------------------------------
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        computes, compares = _hmac_shape(tree)
        writes = _signature_names(root, path, kinds={"dict"})
        if not ((computes and not compares) or writes):
            continue
        out.count("signer_modules")
        if rel in (signer_rel, verifier_rel):
            continue
        out.hit(
            rel,
            0,
            "this module signs an outbound body — it computes an HMAC it never compares, or "
            f"writes an `X-Signature*` header — and {signer_rel} is the one signer. Two "
            "signers do not disagree on the day the second lands; they disagree later, about "
            "a prefix or an encoding or a timestamp, inside somebody else's verifier. Call "
            "the one signer, or take a second scheme through it (house rule 43)",
            root=root,
            klass="signers",
        )

    # --- population B: the census --------------------------------------------
    sent = _signature_names(root, root / signer_rel, kinds={"dict"}) if signer_rel else set()
    received = (
        _signature_names(root, root / receiver_rel, kinds={"call"}) if receiver_rel else set()
    )
    documented = (
        set(_SIGNATURE_NAME_RE.findall(_contract_docstring(root, contract_rel, contract_fn)))
        if contract_rel
        else set()
    )
    out.targets_matched["signature_schemes"] = len(sent)
    sites = (
        ("the delivery writes", signer_rel, sent),
        ("the reference receiver reads", receiver_rel, received),
        ("the contract prose documents", contract_rel, documented),
    )
    for scheme in sorted(sent | received | documented):
        holders = [label for label, _rel, names in sites if scheme in names]
        if len(holders) == len(sites):
            out.count("schemes_censused")
            continue
        missing = [(label, rel) for label, rel, names in sites if scheme not in names]
        out.hit(
            missing[0][1],
            0,
            f"{scheme} is named where {' and '.join(holders) or 'nothing does'} and not where "
            + " and ".join(label for label, _rel in missing)
            + f" — a scheme lives at all three sites or at none. Dropping {scheme} is one "
            "commit that edits all three; this is that commit half-made, and the missing "
            "half is invisible until somebody else's verifier stops matching (house rule 43)",
            root=root,
            klass="census",
        )

    # --- the verifier's own direction: no branch for a scheme nobody sends ----
    verifier_tree = _parse(root / verifier_rel) if verifier_rel else None
    if verifier_tree is not None:
        for node in verifier_tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            found = _VERIFIER_SEAM_RE.match(node.name)
            if not found:
                continue
            out.count("verifier_seams")
            scheme = f"X-Signature-V{found.group(1)}"
            if scheme in sent:
                continue
            out.hit(
                verifier_rel,
                node.lineno,
                f"{node.name} parses {scheme} and no delivery sends it — the signer writes "
                f"{', '.join(sorted(sent)) or 'nothing'}. A verifier branch for a scheme "
                "nothing sends is unreachable code that reads to a reviewer as support for a "
                "scheme this product does not have (house rule 43)",
                root=root,
                klass="census",
            )
    return out


from quality.checks.rule_13_clauses_i_iv import _module_string_constants  # noqa: E402
from quality.checks.rule_36 import _callee_name  # noqa: E402
from quality.checks.rule_42 import _dotted, _import_maps  # noqa: E402
