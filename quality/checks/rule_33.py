"""Rule 33: one door to the search index (ADR search-2, R-a)."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 33: one door to the search index (ADR search-2, R-a) ------------
#
# The rule-27 shape, pointed at a different external system and for a sharper
# reason. Zitadel's fence is about a CREDENTIAL and a transaction boundary;
# this one is about a WALL.
#
# An external index that does not carry the tenant walls is a probing oracle:
# type a word, learn whether somebody else's row contains it. The walls are
# injected by exactly one function (`apps/search/selectors.py`), and that
# sentence is only true while there is exactly one way to reach the engine. A
# second module holding a Meili client is not a style problem — it is a second
# query path with no filter on it, and nothing anywhere would go red.
#
# TWO HALVES, as rule 27 has:
#
# 1. **the credential and the address**: `MEILI_URL` and `MEILI_MASTER_KEY` are
# named in `apps/search/engine.py` (where they are used) and in
# `config/settings/` (where the environment is read), and nowhere else. A
# third reader is a third place a master key can reach a log line, an
# exception message or a subprocess environment — and a fourth way to dial
# the index.
# 2. **the client**: `meilisearch` is imported ONLY by `engine.py`, and
# `apps.search.engine` is imported only from the allow-list below — the
# chokepoint, the write services, the reconcile activity, the backstop
# command and the tests.
#
# Both halves are read from the AST rather than from the text, which is what
# makes the negatives possible: this module's own prose names
# `MEILI_MASTER_KEY` repeatedly, and a check that fired on the word would fire
# on its own reasons.

# : The two names that may not travel. `MEILI_ENV` is deliberately NOT one of
# : them: it selects the server's own mode and is neither an address nor a
# : credential, so refusing it would be the rule getting bigger than its reason.
MEILI_SETTINGS = ("MEILI_URL", "MEILI_MASTER_KEY")

# : The client library the fence exists to confine.
MEILI_PACKAGE = "meilisearch"

# : The module every other module must go through, and never around.
ENGINE_MODULE = "apps.search.engine"
ENGINE_PACKAGE, _, ENGINE_NAME = ENGINE_MODULE.rpartition(".")
MEILI_KLASS = "meili_client"


def _names_meili_setting(node: ast.AST) -> str | None:
    """Which fenced name this node names, or `None`. **Never prose.**

    The three shapes and exactly three: `settings.MEILI_URL` (an attribute), a
    string constant that IS the name (`os.environ["MEILI_URL"]`,
    `env.str("MEILI_URL")`), and a bare binding, which is how a settings module
    declares one. A docstring that mentions the variable is a `Constant` whose
    value is the whole docstring, so EQUALITY — rather than membership — is what
    keeps this silent on documentation.
    """
    if isinstance(node, ast.Attribute) and node.attr in MEILI_SETTINGS:
        return node.attr
    if isinstance(node, ast.Name) and node.id in MEILI_SETTINGS:
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if node.value in MEILI_SETTINGS else None
    return None


def _imports_meili(node: ast.AST) -> bool:
    """Whether this statement pulls in the Meilisearch client library itself."""
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return module == MEILI_PACKAGE or module.startswith(f"{MEILI_PACKAGE}.")
    if isinstance(node, ast.Import):
        return any(
            alias.name == MEILI_PACKAGE or alias.name.startswith(f"{MEILI_PACKAGE}.")
            for alias in node.names
        )
    return False


def _imports_engine(node: ast.AST) -> bool:
    """Whether this statement pulls in the fenced engine module.

    The three shapes a person writes: `from apps.search.engine import x`,
    `from apps.search import engine`, and `import apps.search.engine`.
    """
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module == ENGINE_MODULE or module.startswith(f"{ENGINE_MODULE}."):
            return True
        return module == ENGINE_PACKAGE and any(a.name == ENGINE_NAME for a in node.names)
    if isinstance(node, ast.Import):
        return any(
            a.name == ENGINE_MODULE or a.name.startswith(f"{ENGINE_MODULE}.") for a in node.names
        )
    return False


def meili_client(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    scope = rule.get("scope") or {}
    importers = [str(e.get("path", "")) for e in scope.get("allow_import") or [] if e.get("path")]
    readers = [str(e.get("path", "")) for e in scope.get("allow_secret") or [] if e.get("path")]
    engine_rel = ENGINE_MODULE.replace(".", "/") + ".py"

    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        if rel == engine_rel:
            # The module the rule funnels everything into. Its own client and
            # its own two environment reads are the POINT, and they are counted
            # so that a recogniser which stopped recognising anything trips the
            # floor rather than reporting a clean nothing.
            out.count("engine_module")
            for node in ast.walk(tree):
                if _names_meili_setting(node):
                    out.count("secret_sites")
                elif _imports_meili(node):
                    out.count("client_imports")
            continue

        may_import = any(rel == entry or rel.startswith(entry) for entry in importers)
        may_read = any(rel == entry or rel.startswith(entry) for entry in readers)

        for node in ast.walk(tree):
            named = _names_meili_setting(node)
            if named:
                if may_read:
                    out.count("secret_sites")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"names {named} — the search index's address and master key are read "
                        f"in {engine_rel} and declared in config/settings, and nowhere else. "
                        "A second reader is a second way to dial the index, and the index is "
                        "where the tenant walls are injected. Call apps.search.selectors."
                        "get_search_page(), or add this module to rule 33's allow-list in "
                        "quality/rules.yaml with the reason — the allow-list makes this "
                        "MODULE a standing second reader, where `# rule-33: <reason>` on "
                        "this line exempts this line and is counted and printed on every "
                        "run",
                        klass=MEILI_KLASS,
                    )
                continue
            if _imports_meili(node):
                out.hit(
                    rel,
                    getattr(node, "lineno", 1),
                    f"imports {MEILI_PACKAGE} — the search engine is reached through "
                    f"{engine_rel} and nowhere else. A client here is a query path with no "
                    "scope filter on it: the walls are injected by ONE function "
                    "(apps/search/selectors.py) and an unfenced client is how an index "
                    "becomes a probing oracle. Call apps.search.selectors.get_search_page()",
                    klass=MEILI_KLASS,
                )
                continue
            if not _imports_engine(node):
                continue
            if may_import:
                out.count("engine_importers")
                continue
            out.hit(
                rel,
                getattr(node, "lineno", 1),
                f"imports {ENGINE_MODULE} — the engine takes a ScopeFilter it does not "
                "build, so a caller outside the chokepoint is a caller choosing its own "
                "walls. Reads go through apps.search.selectors.get_search_page(); writes go "
                "through apps.search.services. Or add this module to rule 33's "
                "allow-list in quality/rules.yaml with the reason — which makes this "
                "MODULE a standing importer, where `# rule-33: <reason>` on this import "
                "line exempts this line and is counted and printed on every run",
                klass=MEILI_KLASS,
            )
    return out
