"""The seam pre-flight: verify a brief's `module:callable(fragment)` claims against a checkout.

`scripts/seam_check.sh` refuses a pipe and execs this; this file owns the flags, the root and
its interpreter (it re-execs under the root's `.venv`) and the one question: does the tree have
that callable, with those parameters?

NOT EXECUTABLE, AND THAT IS THE DECLARATION, not an oversight — the same one
`scripts/secrets_scan.sh` makes. This module reports its verdict to whoever ran
it under the RIGHT interpreter; run under the wrong one it would report an
absence that is really a mis-invocation, which is the exact class it exists to
refuse. `seam_check.sh` is the instrument and owns the census row; this is its
body.

---------------------------------------------------------------------------
WHY IT EXISTS. A rung was once dispatched against a brief naming four
`apps/files` seams. Four of them did not exist in the shape the brief claimed;
a builder verified each one, held, and the rung sat ~3h serialized behind a
re-dispatch. Every one of the four was knowable from the baseline tree AT
BRIEF TIME, by anyone willing to import the module and look.

IMPORT, NOT GREP, and the distinction is the whole instrument. A grep for
`def delete_object` answers a question about TEXT: it is fooled by a name in a
docstring, by a re-export, by a definition inside a `if TYPE_CHECKING` block,
by a function the module deletes again three lines later, and — the case that
actually bit — by a name that exists with a DIFFERENT SIGNATURE, which greps
green and holds the rung anyway. An import answers the question the brief is
really asking: can a builder call this. So this module imports through the
baseline checkout's own venv, runs `django.setup()` where the callable lives
under `apps/` or `config/`, and reads `inspect.signature`.

WHAT A VERDICT MEANS HERE, stated so nobody reads more into a green:

  PROVEN       the module imported, the attribute is there, it is callable, and
               every parameter the fragment names is a parameter of it.
  DISPROVEN    it looked, and the claim is false. A finding against the BRIEF,
               not against the tree.
  CANNOT CHECK it could not look at all — no venv, a settings module that will
               not load, a claim it cannot parse, a module that exists and
               explodes on import. **This is exit 2 and it outranks
               everything**, because a claim silently skipped is the failure
               this whole instrument exists to remove: a brief that carries a
               green nobody proved is worse than a brief that carries nothing.

WHAT IT DOES NOT COVER — declared here, printed in the footer of every run, and
repeated in the census row, because a reader who mistakes this for a
correctness check will trust a brief further than the evidence goes:

  1. BEHAVIOR AND SEMANTICS. That `store_bytes` exists and takes `content` says
     nothing about what it does with it, whether it emits, whether it is a
     `@service`, whether it authorizes, or whether it is the right seam for the
     job. The brief still owns all of that.
  2. TYPES BEYOND THE NAME. Annotations are not compared. A fragment naming
     `body` matches a parameter called `body` whatever it is annotated as.
  3. PARAMETER ORDER, and defaults. A fragment is a FRAGMENT: it asserts that
     the names it lists are parameters, not that they are all of them, not that
     they come in that order, and not what they default to.
  4. EXTRA PARAMETERS. A real signature with parameters the fragment does not
     name is PROVEN, deliberately — a brief quoting four of six arguments is
     quoting correctly.
  5. THE CALL ACTUALLY WORKING. Nothing is called. A callable that raises on
     every invocation is PROVEN here.
  6. `**kwargs` ABSORPTION IS NOT A MATCH, and that is deliberate rather than
     an omission: if a name were allowed to match a `**kwargs`, then every
     claim against every `**kwargs` callable would be unfalsifiable, and a
     check that cannot fail is the thing the house rules engine exists against.
     A fragment naming `body` against `f(**kwargs)` is DISPROVEN, and the
     message says why so the brief's author can decide.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import difflib
import importlib
import importlib.util
import inspect
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


def _could_not_look() -> type[Exception]:
    """The shared could-not-look class, imported without leaving this checkout's `apps` behind.

    `quality/could_not_look.py` marks its class with `apps.core.roads.road`, so
    importing it imports `apps` — from THIS file's checkout. This program then
    imports claims from `--root`, which may be another checkout (a baseline), and
    a cached `apps` package would answer those imports from the wrong tree. So
    the root goes on `sys.path` for this one import and comes off again, and
    every `apps` / `quality` module the import cached is evicted except the one
    this program keeps. A claim that names `quality.could_not_look` itself is
    read from this checkout — the one declared cost.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    before = set(sys.modules)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    try:
        from quality.could_not_look import CouldNotLook
    finally:
        if added:
            sys.path.remove(root)
        for name in set(sys.modules) - before:
            if name.split(".", 1)[0] in ("apps", "quality") and name != "quality.could_not_look":
                del sys.modules[name]
    return CouldNotLook


CannotCheck = _could_not_look()

# The two package roots whose modules need Django's app registry populated
# before they can be imported at all. `apps.*` is the obvious half; `config.*`
# is here because a settings-reading module (`config.api`, `config.urls`) is a
# seam a brief names as readily as a service is.
DJANGO_ROOTS = ("apps", "config")

DEFAULT_SETTINGS = "config.settings.local"

# `module.path:qualified.name` with an OPTIONAL parenthesised fragment. The
# qualname is dotted so `module:Class.method` is a first-class claim — an MCP
# tool class or a workflow's `@workflow.run` is exactly the kind of seam a
# brief names.
CLAIM_RE = re.compile(
    r"""^\s*
        (?P<module>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
        :
        (?P<qual>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
        (?:\s*\((?P<frag>.*)\)\s*)?
        \s*$""",
    re.VERBOSE | re.DOTALL,
)


class Verdict(Enum):
    PROVEN = "PROVEN"
    DISPROVEN = "DISPROVEN"
    CANNOT_CHECK = "CANNOT CHECK"


class Disproven(Exception):
    """It looked, and the claim is false."""


class TokenKind(Enum):
    NAMED = "named"
    VAR_POSITIONAL = "*args"
    VAR_KEYWORD = "**kwargs"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    name: str
    # True when the token appeared AFTER a bare `*` in the fragment, which is
    # the brief asserting keyword-only. Absent `*`, nothing is asserted about
    # kind — see blind spot 3.
    keyword_only: bool = False


@dataclass
class Claim:
    raw: str
    module: str = ""
    qual: str = ""
    tokens: list[Token] = field(default_factory=list)
    has_fragment: bool = False
    verdict: Verdict = Verdict.CANNOT_CHECK
    detail: str = ""
    signature: str = ""


# --- parsing ------------------------------------------------------------------


def split_top_level(text: str) -> list[str]:
    """Split a fragment on commas that are not inside brackets or a string.

    A default or an annotation legitimately contains commas — `x: dict[str, int]`,
    `y=(1, 2)` — and splitting naively turns one parameter into two phantom ones
    that are then reported absent. A depth counter is enough here; this is not
    Python parsing and does not pretend to be, which is why an unbalanced
    fragment is CANNOT CHECK rather than a guess.
    """
    parts: list[str] = []
    depth = 0
    quote = ""
    buf: list[str] = []
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                raise CannotCheck("the fragment's brackets do not balance")
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if depth != 0:
        raise CannotCheck("the fragment's brackets do not balance")
    if quote:
        raise CannotCheck("the fragment has an unclosed string")
    parts.append("".join(buf))
    return parts


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_fragment(frag: str) -> list[Token]:
    """`*, tenant, key` and `self, *args, **kwargs` and `x: int = 3` all parse.

    A bare `*` switches every later token to keyword-only. A bare `/` is
    accepted and ignored — positional-only is a real Python marker and a brief
    is entitled to quote it, but nothing here checks it (blind spot 3).
    """
    tokens: list[Token] = []
    kw_only = False
    if not frag.strip():
        return tokens
    for piece in split_top_level(frag):
        raw = piece.strip()
        if not raw:
            # `f(a,)` — a trailing comma is ordinary Python, not a claim.
            continue
        if raw == "*":
            kw_only = True
            continue
        if raw == "/":
            continue
        kind = TokenKind.NAMED
        if raw.startswith("**"):
            kind, raw = TokenKind.VAR_KEYWORD, raw[2:]
        elif raw.startswith("*"):
            kind, raw = TokenKind.VAR_POSITIONAL, raw[1:]
        # Drop an annotation or a default; only the NAME is compared, and
        # blind spot 2 says so out loud.
        name = re.split(r"[:=]", raw, maxsplit=1)[0].strip()
        if not IDENT_RE.match(name):
            raise CannotCheck(
                f"`{piece.strip()}` is not a parameter this reader can name — a fragment is a "
                f"comma-separated list of parameter names, optionally with `*`, `**`, an "
                f"annotation or a default"
            )
        tokens.append(Token(kind=kind, name=name, keyword_only=kw_only))
    return tokens


def parse_claim(raw: str) -> Claim:
    claim = Claim(raw=raw.strip())
    m = CLAIM_RE.match(raw)
    if m is None:
        raise CannotCheck(
            "not a claim this reader can parse — the form is "
            "`module.path:callable(fragment)`, and the fragment may be empty"
        )
    claim.module = m.group("module")
    claim.qual = m.group("qual")
    frag = m.group("frag")
    claim.has_fragment = frag is not None
    claim.tokens = parse_fragment(frag or "")
    return claim


# --- the import machinery -----------------------------------------------------


class Importer:
    """Owns `django.setup()` — once, lazily, and loudly when it will not run."""

    def __init__(self, root: str, settings: str) -> None:
        self.root = root
        self.settings = settings
        self.django_state = "not needed"
        self._django_ready = False
        self._django_error = ""

    def needs_django(self, module: str) -> bool:
        head = module.split(".", 1)[0]
        return head in DJANGO_ROOTS

    def ensure_django(self) -> None:
        if self._django_ready:
            return
        if self._django_error:
            raise CannotCheck(self._django_error)
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", self.settings)
        try:
            import django

            django.setup()
        except BaseException as exc:  # noqa: BLE001 - see below
            # DELIBERATELY BaseException. A settings module that cannot resolve
            # a database name raises `ImproperlyConfigured`; one that calls
            # `sys.exit` raises `SystemExit`, which is NOT an `Exception` and
            # would otherwise leave this process exiting 1 with no verdict
            # printed — a claim silently skipped, wearing a plausible status.
            self._django_error = (
                f"the import machinery is unavailable: `django.setup()` with "
                f"DJANGO_SETTINGS_MODULE={os.environ.get('DJANGO_SETTINGS_MODULE')} raised "
                f"{type(exc).__name__}: {exc}. Nothing was judged — this is not a claim "
                f"about the seam."
            )
            self.django_state = "FAILED"
            raise CannotCheck(self._django_error) from exc
        self._django_ready = True
        self.django_state = f"ran ({os.environ.get('DJANGO_SETTINGS_MODULE')})"

    def import_module(self, module: str):  # noqa: ANN201 - a module object
        if self.needs_django(module):
            self.ensure_django()

        # `find_spec` is what separates the two answers that must never share a
        # code path: "there is no such module" (the claim is FALSE) from "the
        # module is there and blew up" (this reader COULD NOT LOOK). Without
        # the split, a broken transitive import reads exactly like a seam that
        # was never built, and the brief's author fixes the wrong thing.
        try:
            spec = importlib.util.find_spec(module)
        except ModuleNotFoundError:
            # A missing PARENT package. `apps.nosuch.storage` lands here, and
            # it is an absence like any other.
            spec = None
        except BaseException as exc:  # noqa: BLE001
            raise CannotCheck(
                f"`{module}` could not even be looked for: importing its parent package raised "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if spec is None:
            raise Disproven(f"there is no module `{module}` importable from this checkout")
        try:
            return importlib.import_module(module)
        except BaseException as exc:  # noqa: BLE001
            raise CannotCheck(
                f"`{module}` exists and could not be imported: {type(exc).__name__}: {exc}. "
                f"Nothing was judged about the callable."
            ) from exc


# --- the check ----------------------------------------------------------------


def resolve(mod: object, module_name: str, qual: str) -> object:
    obj: object = mod
    walked: list[str] = []
    for part in qual.split("."):
        if not hasattr(obj, part):
            where = f"`{module_name}" + ("." + ".".join(walked) if walked else "") + "`"
            near = difflib.get_close_matches(
                part, [n for n in dir(obj) if not n.startswith("_")], 3
            )
            hint = f" Nearest names there: {', '.join(near)}." if near else ""
            raise Disproven(f"{where} has no attribute `{part}`.{hint}")
        obj = getattr(obj, part)
        walked.append(part)
    return obj


def check_signature(obj: object, claim: Claim) -> str:
    try:
        sig = inspect.signature(obj)  # type: ignore[arg-type]
    except (ValueError, TypeError) as exc:
        if not claim.tokens:
            # Existence was the whole claim, and existence is proven. A C
            # builtin with no introspectable signature is not a finding.
            return "<no introspectable signature>"
        raise CannotCheck(
            f"`{claim.module}:{claim.qual}` exists and callable, but its signature cannot be "
            f"read ({type(exc).__name__}: {exc}) — so the fragment was compared against "
            f"nothing. Re-state the claim with an empty fragment to assert existence alone."
        ) from exc

    params = sig.parameters
    var_pos = [p for p in params.values() if p.kind is inspect.Parameter.VAR_POSITIONAL]
    var_kw = [p for p in params.values() if p.kind is inspect.Parameter.VAR_KEYWORD]
    rendered = str(sig)

    for tok in claim.tokens:
        if tok.kind is TokenKind.VAR_POSITIONAL:
            if not var_pos:
                raise Disproven(
                    f"the fragment claims `*{tok.name}`; the real signature {rendered} takes no "
                    f"variadic positional argument"
                )
            continue
        if tok.kind is TokenKind.VAR_KEYWORD:
            if not var_kw:
                raise Disproven(
                    f"the fragment claims `**{tok.name}`; the real signature {rendered} takes no "
                    f"variadic keyword argument"
                )
            continue

        found = params.get(tok.name)
        if found is None or found.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            extra = ""
            if var_kw:
                extra = (
                    f" It does take `**{var_kw[0].name}`, which is NOT accepted as a match here: "
                    f"a name that any `**kwargs` satisfies is a claim that cannot fail."
                )
            near = difflib.get_close_matches(tok.name, list(params), 3)
            hint = f" Nearest parameters: {', '.join(near)}." if near else ""
            raise Disproven(
                f"the fragment names `{tok.name}`, which is not a parameter of {rendered}."
                f"{hint}{extra}"
            )
        if tok.keyword_only and found.kind is not inspect.Parameter.KEYWORD_ONLY:
            raise Disproven(
                f"the fragment places `{tok.name}` after a bare `*` (keyword-only); in "
                f"{rendered} it is {found.kind.description}"
            )
    return rendered


def check(claim: Claim, importer: Importer) -> None:
    try:
        mod = importer.import_module(claim.module)
        obj = resolve(mod, claim.module, claim.qual)
        if not callable(obj):
            raise Disproven(
                f"`{claim.module}:{claim.qual}` exists, but it is a {type(obj).__name__} and is "
                f"not callable — a seam a brief names is something a builder can call"
            )
        claim.signature = check_signature(obj, claim)
        claim.verdict = Verdict.PROVEN
    except Disproven as exc:
        claim.verdict = Verdict.DISPROVEN
        claim.detail = str(exc)
    except CannotCheck as exc:
        claim.verdict = Verdict.CANNOT_CHECK
        claim.detail = str(exc)


# --- the report ---------------------------------------------------------------

BLIND_SPOTS = (
    "This proves EXISTENCE and the parameter NAMES a fragment lists. It proves nothing about "
    "behaviour, semantics, types, parameter order, defaults, or whether the seam is the RIGHT "
    "one — the brief still owns all of that (scripts/seam_check.py, module docstring)."
)


def report(claims: list[Claim], root: str, importer: Importer, verbose: bool) -> int:
    proven = [c for c in claims if c.verdict is Verdict.PROVEN]
    bad = [c for c in claims if c.verdict is Verdict.DISPROVEN]
    blind = [c for c in claims if c.verdict is Verdict.CANNOT_CHECK]

    out = sys.stdout
    print(f"seam-check: {len(claims)} claim(s), imported from {root}", file=out)
    # The wrapper resolved the tree; it is here rather than there so the whole
    # preamble a PM pastes into a brief arrives as one block.
    print(f"  tree:     {os.environ.get('SEAM_CHECK_TREE', '(not a git checkout)')}", file=out)
    print(f"  python:   {sys.executable}", file=out)
    print(f"  django:   {importer.django_state}", file=out)

    # A PROVEN claim says NOTHING here by default. The one thing this
    # instrument must never do is add a line of noise per true claim, because a
    # brief's seam block is meant to be pasted and read.
    if verbose:
        for c in proven:
            print(f"  proven:   {c.raw}   ->   {c.qual}{c.signature}", file=out)

    for c in bad:
        print("", file=out)
        print(f"!! DISPROVEN     {c.raw}", file=out)
        print(f"   {c.detail}", file=out)
    for c in blind:
        print("", file=out)
        print(f"!! CANNOT CHECK  {c.raw}", file=out)
        print(f"   {c.detail}", file=out)

    print("", file=out)
    if blind:
        print(
            f"VERDICT: COULD NOT LOOK — {len(blind)} of {len(claims)} claim(s) were not checked "
            f"at all ({len(proven)} proven, {len(bad)} disproven).",
            file=out,
        )
        print(
            "  A claim nobody checked must never reach a brief as a green. Fix the "
            "environment or the claim and run it again.",
            file=out,
        )
        return 2
    if bad:
        print(
            f"VERDICT: {len(bad)} of {len(claims)} claim(s) DISPROVEN — this baseline tree does "
            f"not have the seam the brief names.",
            file=out,
        )
        print(
            "  That is a finding against the BRIEF, not against the tree: fix the brief, or "
            "dispatch the seam first. It is the FLAG-AND-HOLD this instrument exists to "
            "spend one second on instead of three hours (docs/product/in-flight.md:195).",
            file=out,
        )
        return 1
    print(f"VERDICT: all {len(claims)} claim(s) PROVEN against this tree.", file=out)
    print(f"  {BLIND_SPOTS}", file=out)
    return 0


# --- entry --------------------------------------------------------------------


USAGE = """usage: seam_check.sh [--root DIR] [--settings MODULE] [--claims FILE] [--verbose] \\
                     [CLAIM ...]
  CLAIM         module.path:callable(fragment)   — the fragment may be empty
                module.path:Class.method(fragment)
  --claims FILE one claim per line; `#` starts a comment; `-` reads stdin
  --root DIR    the checkout to import FROM (default: this script's checkout)
  --settings M  DJANGO_SETTINGS_MODULE for claims under apps/ or config/
  --verbose     also print each PROVEN claim with the signature it resolved to
exit: 0 all proven · 1 a claim is false · 2 could not look (2 outranks a pass)"""

NOTHING_JUDGED = "Nothing was checked; no claim was judged."


def _refuse(sentence: str) -> int:
    print(f"!! seam_check: {sentence}\n   {NOTHING_JUDGED}", file=sys.stderr)
    return 2


def _claims_file(src: str) -> list[str] | None:
    """The claims a `--claims` file holds, comments and blanks dropped; None when unreadable."""
    try:
        text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    except OSError:
        return None
    kept = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return [claim for claim in kept if claim]


def _root_environment(root: str) -> None:
    """The tree line, and the checkout's derived DATABASE_NAME (scripts/db.sh) for its settings."""
    git = ["git", "-C", root, "rev-parse", "--short", "HEAD"]
    tree = subprocess.run(git, capture_output=True, text=True)
    os.environ["SEAM_CHECK_TREE"] = (
        tree.stdout.strip() if tree.returncode == 0 else "(not a git checkout)"
    )
    if not os.environ.get("DATABASE_NAME") and Path(root, "scripts/db.sh").is_file():
        name = subprocess.run(
            ["bash", "-c", '. scripts/db.sh >/dev/null 2>&1; printf %s "${DATABASE_NAME:-}"'],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if name.stdout:
            os.environ["DATABASE_NAME"] = name.stdout


def main(argv: list[str]) -> int:
    root = str(Path(__file__).resolve().parent.parent)
    settings = DEFAULT_SETTINGS
    verbose = False
    raws: list[str] = []
    it = iter(argv)
    for arg in it:
        if arg in ("-h", "--help"):
            print(USAGE)
            return 0
        if arg in ("--root", "--settings", "--claims"):
            value = next(it, "")
            if not value:
                return _refuse(f"{arg} needs a value.")
            if arg == "--root":
                root = value
            elif arg == "--settings":
                settings = value
            else:
                read = _claims_file(value)
                if read is None:
                    return _refuse(f"--claims {value}: no such readable file.")
                raws.extend(read)
        elif arg in ("--verbose", "-v"):
            verbose = True
        elif arg == "--":
            raws.extend(it)
            break
        elif arg.startswith("-"):
            return _refuse(f"unknown option '{arg}' — `--help` names the flags.")
        else:
            raws.append(arg)

    if not Path(root).is_dir():
        return _refuse(f"--root {root} is not a directory.")
    root = str(Path(root).resolve())
    py = Path(root, ".venv/bin/python")
    if not py.is_file():
        return _refuse(
            f"{root} has no .venv/bin/python — the claims are imported through the BASELINE "
            "CHECKOUT'S OWN venv and no other. Run `uv sync` (or ./scripts/setup.sh) there first."
        )
    # The claims are imported through the root's own interpreter: re-exec under it, once.
    under_root = Path(sys.prefix).resolve() == Path(root, ".venv").resolve()
    if not under_root and not os.environ.get("SEAM_CHECK_REEXEC"):
        os.environ["SEAM_CHECK_REEXEC"] = "1"
        os.execv(str(py), [str(py), str(Path(__file__).resolve()), *argv])  # noqa: S606 — re-execs this script under the venv's interpreter, fixed paths
    if not raws:
        print(f"!! no claims were given — checking nothing is no pass.\n{USAGE}", file=sys.stderr)
        return 2

    os.chdir(root)
    _root_environment(root)
    if root not in sys.path:
        sys.path.insert(0, root)

    importer = Importer(root=root, settings=settings)
    claims: list[Claim] = []
    for raw in raws:
        try:
            claim = parse_claim(raw)
        except CannotCheck as exc:
            claims.append(Claim(raw=raw.strip(), verdict=Verdict.CANNOT_CHECK, detail=str(exc)))
            continue
        check(claim, importer)
        claims.append(claim)

    return report(claims, root, importer, verbose)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
