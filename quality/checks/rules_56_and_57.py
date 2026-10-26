"""Rules 56 and 57: one router, one writer of the identity join."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files, _read

# --- rules 56 and 57: one router, one writer of the identity join ------------
#
# Two rules, one shape, and the shape is rule 27's: a question that must have
# ONE answering module, an allow-list of paths each carrying a reason, a valve
# counted and printed, and a floor on the population so a recogniser that stops
# seeing its own subject trips rather than reporting a clean nothing.
#
# WHY TWO IDS AND NOT ONE. They fence two different tables against two
# different failures. A second home-realm router is one person sent to one
# identity provider and provisioned into another tenant; a second writer of the
# identity join is an account takeover with an extra step. The remedies differ,
# the allow-lists differ, and a reader holding one red must not have to work out
# which half of a compound statement they are in.

#: The two manager methods that ARE home-realm discovery, and the keyword that
#: is the same question written out longhand.
_ROUTER_METHOD = "for_domain"
_CLAIM_METHOD = "claim"
_DOMAIN_MODEL = "SsoDomain"
#: The identity join: `SsoIdentity` rows whose `connection` is `None`, keyed
#: `(realm, subject)`. A row is written by constructing one, or by a manager
#: create carrying `connection=None`; it is moved or cleared by an `update(` or
#: `delete(` on a chain that narrowed to `connection__isnull`.
_JOIN_MODEL = "SsoIdentity"
_JOIN_KEYWORD = "connection"
_JOIN_NARROWING = "connection__isnull"
_JOIN_WRITE_CALLS = ("create", "get_or_create", "update_or_create")
_JOIN_BULK_CALLS = ("update", "delete")
#: The two manager methods a caller reads the join through.
_JOIN_READS = ("in_realm", "of_subject")
#: The join row's key fields. Fetching a row and setting one of these re-points
#: which account a subject signs in as — the classic bypass of a one-writer rule.
_JOIN_KEY_FIELDS = ("user", "user_id", "subject", "realm")
#: The reverse accessor from a person to their join rows.
_JOIN_REVERSE = "sso_identities"


def _reads_the_join(expr: ast.expr) -> bool:
    """Whether an expression fetches join rows: a chain from `SsoIdentity` or `.sso_identities`."""
    node: ast.expr = expr
    while isinstance(node, (ast.Call, ast.Attribute, ast.Subscript)):
        if isinstance(node, ast.Attribute) and node.attr == _JOIN_REVERSE:
            return True
        node = node.func if isinstance(node, ast.Call) else node.value
    return isinstance(node, ast.Name) and node.id == _JOIN_MODEL


def _join_rows_bound(tree: ast.AST) -> set[str]:
    """The local names a module binds to a fetched join row (or rows)."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _reads_the_join(node.value):
            bound.update(one.id for one in node.targets if isinstance(one, ast.Name))
        elif isinstance(node, ast.For) and _reads_the_join(node.iter):
            if isinstance(node.target, ast.Name):
                bound.add(node.target.id)
    return bound


#: allauth's own link. Recognised on the receiver NAME rather than on the
#: method alone, because `Client.connect(` is Temporal's and `Client.connect(`
#: is also the health probe's — a rule that fenced every `.connect(` in the
#: tree would be a rule about a word.
_SOCIALLOGIN = "sociallogin"


def _allowed_paths(rule: dict, key: str) -> set[str]:
    """The paths a scope allow-list names. Each entry carries its own reason."""
    return {
        str(entry["path"])
        for entry in (rule.get("scope") or {}).get(key) or []
        if entry.get("path")
    }


def _receiver_names(node: ast.Call) -> tuple[str, str]:
    """(the attribute called, the chain root's name) for an Attribute call."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return "", ""
    root = _chain_root(func.value)
    return func.attr, _callee_name(root) or ""


def home_realm_router(root: Path, rule: dict) -> CheckResult:
    """Rule 56. One question, one answering module.

    The recogniser is rule 8's, pointed at a different manager: a call whose
    receiver chain ends in a `Name` that IS the model — `SsoDomain.objects
    .for_domain(...)` — plus the longhand form, a `filter(`/`get(` carrying a
    `domain=` keyword on the same chain. A module that never mentions the model
    cannot be a second router, so the population is the modules that do.
    """
    out = CheckResult()
    routers = _allowed_paths(rule, "allow_router")
    claimers = _allowed_paths(rule, "allow_claim")
    out.targets_matched["router_sites"] = 0
    out.targets_matched["claim_sites"] = 0
    out.targets_matched["definition"] = 0
    for path in _py_files(root, "apps") + _py_files(root, "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = path.relative_to(root).as_posix()
        src = _read(path)
        if _DOMAIN_MODEL not in src:
            continue
        # The DEFINITION is not a call site and is counted separately: a
        # manager method has to live somewhere, and the module it lives in is
        # the one place a call-shaped rule would otherwise report as a router.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
                _ROUTER_METHOD,
                _CLAIM_METHOD,
            ):
                out.count("definition")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            attr, receiver = _receiver_names(node)
            longhand = attr in ("filter", "get") and any(
                keyword.arg == "domain" for keyword in node.keywords
            )
            if receiver != _DOMAIN_MODEL and not (longhand and receiver == _DOMAIN_MODEL):
                continue
            if attr == _ROUTER_METHOD:
                out.count("router_sites")
                if rel in routers:
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"{_DOMAIN_MODEL}.objects.{_ROUTER_METHOD}( outside the two pre-auth "
                    "selectors — home-realm discovery is one question with one answer, and a "
                    "second router is one person sent to one identity provider and "
                    "provisioned into another tenant. Reach it through "
                    "`apps.accounts.selectors`",
                )
            elif attr == _CLAIM_METHOD:
                out.count("claim_sites")
                if rel in claimers:
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"{_DOMAIN_MODEL}.objects.{_CLAIM_METHOD}( outside the claim writers — a "
                    "claim reserves a name for a tenant, and a second place that reserves "
                    "one is two tenants owning one address space",
                )
            elif longhand:
                if rel in routers | claimers:
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"{_DOMAIN_MODEL} filtered by `domain=` outside the router — the same "
                    "question written longhand is the same question, and a rule that read "
                    "only the manager method would be a rule about a method name",
                )
    return out


def _names_a_join_row(node: ast.Call) -> bool:
    """A call carrying `connection=None` — the identity join's row, not a connection's."""
    return any(
        keyword.arg == _JOIN_KEYWORD
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is None
        for keyword in node.keywords
    )


def _narrowed_to_the_join(expr: ast.expr) -> bool:
    """Whether a receiver chain narrowed to `connection__isnull` on its way."""
    while isinstance(expr, (ast.Call, ast.Attribute)):
        if isinstance(expr, ast.Call):
            if any(keyword.arg == _JOIN_NARROWING for keyword in expr.keywords):
                return True
            expr = expr.func
        else:
            expr = expr.value
    return False


def _join_write(node: ast.Call) -> str:
    """How this call writes the identity join, or `""` when it does not."""
    func = node.func
    if isinstance(func, ast.Name) and func.id == _JOIN_MODEL and _names_a_join_row(node):
        return f"constructs a `{_JOIN_MODEL}` join row"
    attr, receiver = _receiver_names(node)
    if attr in _JOIN_WRITE_CALLS and receiver == _JOIN_MODEL and _names_a_join_row(node):
        return f"writes a join row through `{_JOIN_MODEL}.objects.{attr}(`"
    if (
        attr in _JOIN_BULK_CALLS
        and isinstance(func, ast.Attribute)
        and _narrowed_to_the_join(func.value)
    ):
        return f"moves or clears join rows through .{attr}( on a `{_JOIN_NARROWING}` chain"
    return ""


def identity_join_writers(root: Path, rule: dict) -> CheckResult:
    """Rule 57. One writer of which subject signs in as which of our people.

    The join is `SsoIdentity` rows with no connection, one per realm a person
    holds a subject in. READS ARE OUT BY CONSTRUCTION and a negative pins it:
    `SsoIdentity.objects.of_subject(…)` resolves a person by their subject and
    is exactly what every door should do. What is fenced is the WRITE — a join
    row constructed or created (`connection=None`), an `update(`/`delete(` on a
    chain narrowed to the join, a fetched join row's key re-set (`row.user =`,
    `.subject =`, `.realm =` on a name bound from `SsoIdentity…` or
    `.sso_identities…`), and allauth's own `sociallogin.connect(`.
    """
    out = CheckResult()
    column = _allowed_paths(rule, "allow_column")
    connect = _allowed_paths(rule, "allow_connect")
    out.targets_matched["column_writers"] = 0
    out.targets_matched["connect_sites"] = 0
    out.targets_matched["column_reads_seen"] = 0
    for path in _py_files(root, "apps") + _py_files(root, "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = path.relative_to(root).as_posix()
        rows = _join_rows_bound(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and rows:
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr in _JOIN_KEY_FIELDS
                        and isinstance(target.value, ast.Name)
                        and target.value.id in rows
                    ):
                        out.count("column_writers")
                        if rel not in column:
                            out.hit(
                                rel,
                                node.lineno,
                                f"sets `.{target.attr}` on a fetched join row outside the "
                                "audited writer — re-pointing a row is writing the identity "
                                "join, and `record_identity` is its one writer",
                            )
                continue
            if not isinstance(node, ast.Call):
                continue
            how = _join_write(node)
            if how:
                out.count("column_writers")
                if rel not in column:
                    out.hit(
                        rel,
                        node.lineno,
                        f"{how} outside the audited writer — which subject signs in as "
                        "which of our people is written by `record_identity` and cleared "
                        "by `unlink_zitadel_identity`, and a second writer is how a join "
                        "between two identity systems comes to disagree with itself",
                    )
                continue
            attr, receiver = _receiver_names(node)
            if attr in _JOIN_READS:
                # A READ, and counted rather than ignored: a recogniser that
                # stopped seeing the join at all would report a clean nothing,
                # and the floor on this number is what says so.
                out.count("column_reads_seen")
                continue
            if attr == "connect" and receiver == _SOCIALLOGIN:
                out.count("connect_sites")
                if rel in connect:
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    "calls `sociallogin.connect(` outside the adapter — allauth's own link "
                    "runs AFTER our writer has said yes, and a call from anywhere else is a "
                    "second join written in a second order",
                )
    return out


from quality.checks.rule_36 import _callee_name  # noqa: E402
from quality.checks.rules_10_12 import _chain_root  # noqa: E402
