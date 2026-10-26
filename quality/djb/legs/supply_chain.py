"""The `supply-chain` leg: advisories, licences and the whole-tree secret scan, 0/1/2."""

# Invariant: one retry, and only on the network's shape with no finding in the text — principle 4.
# does-not-cover: an advisory source that answers clean and lies — the leg believes a clean report.

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from quality.djb.legs._run import say
from quality.djb.registry import Ctx, Leg

#: The network's shape, for both advisory readers and the frontend install.
NETWORK = re.compile(
    r"ReadTimeout|ConnectTimeout|ConnectionError|ProxyError|MaxRetryError|SSLError|"
    r"RemoteDisconnected|Max retries exceeded|timed out|Failed to establish a new connection|"
    r"Temporary failure in name resolution|Name or service not known|nodename nor servname|"
    r"Network is unreachable|Connection (refused|reset|aborted)|ECONNREFUSED|ECONNRESET|"
    r"ETIMEDOUT|ENOTFOUND|EAI_AGAIN|ERR_PNPM_AUDIT|FetchError|fetch failed|getaddrinfo|"
    r"socket hang up",
    re.IGNORECASE,
)
#: What a report of findings looks like in each tool's text; read before the network's shape.
PIP_FINDING = re.compile(r"known vulnerabilit|Fix Versions", re.IGNORECASE)
PNPM_FINDING = re.compile(
    r"│ (info|low|moderate|high|critical) +│|vulnerabilities found", re.IGNORECASE
)
PNPM_INSTALL_FINDING = re.compile(
    r"ERR_PNPM_OUTDATED_LOCKFILE|ERR_PNPM_LOCKFILE_CONFIG_MISMATCH", re.IGNORECASE
)
#: The frontend audit's level.
AUDIT_LEVEL = "moderate"
PIP_AUDIT = ("uv", "run", "pip-audit", "--skip-editable", "--timeout", "60")
SECRETS = ("uv", "run", "detect-secrets-hook", "--baseline", ".secrets.baseline")
ARGV = (PIP_AUDIT, SECRETS, ("uv", "run", "pip-licenses", "--format=json"))

#: Installed ahead of every reader: an uncaught exception is exit 2 naming the reader.
GUARD = """import os as _sc_os, sys as _sc_sys, traceback as _sc_tb
def _sc_crashed(kind, value, tb):
    _sc_sys.stdout.flush()
    reader = _sc_os.environ.get("SUPPLY_CHAIN_READER", "a reader")
    print(
        f"!! SUPPLY CHAIN UNPROVEN — {reader} raised {kind.__name__} ({value}); nothing was judged",
        file=_sc_sys.stderr,
        flush=True,
    )
    _sc_tb.print_exception(kind, value, tb)
    _sc_sys.stderr.flush()
    _sc_os._exit(2)
_sc_sys.excepthook = _sc_crashed
"""

_POLICY = """import os
import sys
sys.path.insert(0, os.environ.get("DJB_SUPPLY_CHAIN_POLICY_DIR") or "scripts")
"""

POLICY_PAIR = (
    _POLICY
    + """from datetime import date
from supply_chain_policy import (
    ADVISORY_EXCEPTIONS,
    MUST_ACCEPT,
    MUST_ACCEPT_ADVISORIES,
    MUST_REFUSE,
    MUST_REFUSE_ADVISORIES,
    advisory_pair_failures,
    banned,
    exception_failures,
    judge_advisory,
    pair_failures,
)
wrong = pair_failures(banned)
wrong += advisory_pair_failures(judge_advisory)
broken = exception_failures(ADVISORY_EXCEPTIONS, date.today())
wrong += [f"the declared exception {s}" for s in broken]
if wrong:
    print(
        "!! SUPPLY CHAIN ENFORCEMENT BROKEN — the supply-chain policy misjudged its own canary"
        " pairs or declares a malformed exception, so no verdict below could be believed:",
        file=sys.stderr,
    )
    for sentence in wrong:
        print(f"   {sentence}", file=sys.stderr)
    print("   EXIT 2 — enforcement broken, before any real package was judged.", file=sys.stderr)
    sys.exit(2)
print(
    f"  licence policy: the canary pair holds ({len(MUST_REFUSE)} refused"
    f" · {len(MUST_ACCEPT)} accepted"
    " through scripts/supply_chain_policy.py)"
)
print(
    f"  advisory policy: the canary pair holds ({len(MUST_REFUSE_ADVISORIES)} refused"
    f" · {len(MUST_ACCEPT_ADVISORIES)} accepted; exceptions declared: {len(ADVISORY_EXCEPTIONS)})"
)
"""
)

PNPM_AUDIT = (
    _POLICY
    + """import json
from collections import Counter
from datetime import date
from supply_chain_policy import judge_advisory
path, level = sys.argv[1], sys.argv[2]
order = ["info", "low", "moderate", "high", "critical"]
floor = order.index(level)
try:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
except (OSError, ValueError) as exc:
    print(f"  pnpm audit: no JSON report on stdout ({type(exc).__name__})")
    sys.exit(3)
if isinstance(doc, dict) and isinstance(doc.get("error"), dict):
    err = doc["error"]
    print(f"  pnpm audit: an error object, not a report — {err.get('code')}: {err.get('message')}")
    sys.exit(3)
meta = doc.get("metadata") if isinstance(doc, dict) else None
if not (
    isinstance(doc, dict)
    and isinstance(doc.get("advisories"), dict)
    and isinstance(meta, dict)
    and isinstance(meta.get("vulnerabilities"), dict)
):
    shape = sorted(doc)[:6] if isinstance(doc, dict) else type(doc).__name__
    print(f"  pnpm audit: the document is not an audit report (read: {shape})")
    sys.exit(3)
def at_level(severity):
    return severity not in order or order.index(severity) >= floor
records = [a for a in doc["advisories"].values() if isinstance(a, dict)]
found = [a for a in records if at_level(a.get("severity"))]
today = date.today()
accepted, refused = [], []
for a in sorted(found, key=lambda a: (str(a.get("module_name")), str(a.get("url")))):
    ok, sentence = judge_advisory(a, today)
    (accepted if ok else refused).append((a, sentence))
for _, sentence in accepted:
    print(f"  {sentence}")
if refused:
    print(f"  pnpm audit: advisories at {level} and above, one per record:")
    for a, sentence in refused:
        rows = [f for f in a.get("findings") or [] if isinstance(f, dict)]
        versions = sorted({str(f.get("version")) for f in rows})
        print(
            f"    {a.get('severity')}  {a.get('module_name')}@{','.join(versions) or '?'}"
            f"  (vulnerable {a.get('vulnerable_versions')})  {a.get('title')}  {a.get('url')}"
        )
        print(f"      {sentence}")
    sys.exit(1)
waived = Counter(a.get("severity") for a, _ in accepted)
left = {k: v - waived[k] for k, v in meta["vulnerabilities"].items() if at_level(k)}
counts = {k: v for k, v in left.items() if v > 0}
if counts:
    named = " ".join(f"{k}={v}" for k, v in counts.items())
    print("advisories reported by count and not by record: " + named)
    sys.exit(1)
below = len(records) - len(found)
print(
    f"  pnpm audit: clean at {level} and above ({meta.get('totalDependencies')} dependencies;"
    f" {below} advisories below {level}; {len(accepted)} accepted by declared exception)"
)
sys.exit(4 if accepted else 0)
"""
)

OVERRIDE_TRIGGER = """import importlib.metadata as md
import json
import sys
import tomllib
import urllib.request
from packaging.requirements import Requirement
with open("pyproject.toml", "rb") as fh:
    overrides = tomllib.load(fh).get("tool", {}).get("uv", {}).get("override-dependencies", [])
if not any(Requirement(o).name == "oauthlib" for o in overrides):
    sys.exit(0)
def cap_lifted(requires):
    for line in requires or []:
        req = Requirement(line)
        social = req.marker is None or req.marker.evaluate({"extra": "socialaccount"})
        if req.name == "oauthlib" and social:
            return req.specifier.contains("4.0.0", prereleases=False), str(req.specifier)
    return True, "(no oauthlib requirement on the socialaccount extra)"
lifted, spec = cap_lifted(md.requires("django-allauth"))
installed = md.version("django-allauth")
if lifted:
    print(f"!! the oauthlib override in pyproject.toml is DEAD WEIGHT: the installed "
          f"django-allauth {installed} declares oauthlib{spec}, which admits 4 — delete the "
          "override", file=sys.stderr)
    sys.exit(1)
data = None
for attempt in (1, 2):
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/django-allauth/json", timeout=60) as r:
            data = json.load(r)
        break
    except OSError as exc:
        print(f"  the index could not be read (attempt {attempt}): {exc}")
if data is None:
    print("!! SUPPLY CHAIN UNPROVEN — could not read django-allauth's newest release from the "
          "index, so whether the oauthlib override is still forced was not judged", file=sys.stderr)
    sys.exit(2)
latest = data["info"]["version"]
lifted, latest_spec = cap_lifted(data["info"].get("requires_dist"))
if lifted:
    print(f"!! the oauthlib override in pyproject.toml has FIRED: django-allauth {latest} declares "
          f"oauthlib{latest_spec}, which admits 4 — upgrade django-allauth and delete the override",
          file=sys.stderr)
    sys.exit(1)
print(f"  oauthlib override still forced: django-allauth {installed} (installed) declares "
      f"oauthlib{spec}, {latest} (newest) declares oauthlib{latest_spec}")
"""

PYTHON_LICENCES = (
    _POLICY
    + """import json
import subprocess
from supply_chain_policy import banned
out = subprocess.run(["uv", "run", "pip-licenses", "--format=json"], capture_output=True, text=True)
if out.returncode != 0:
    print(f"!! SUPPLY CHAIN UNPROVEN — pip-licenses exited {out.returncode}; no Python licence "
          "was judged", file=sys.stderr)
    print(out.stderr, file=sys.stderr)
    sys.exit(2)
rows = json.loads(out.stdout)
bad = [f"{row['Name']} ({row['License']})" for row in rows if banned(row["License"])]
if bad:
    print("copyleft dependencies found:", ", ".join(bad))
    sys.exit(1)
print(f"licenses clean ({len(rows)} packages)")
"""
)

FRONTEND_LICENCES = (
    _POLICY
    + r"""import json
import re
from supply_chain_policy import banned
doc_path, frontend, rc, py_sentence = sys.argv[1:5]
root = os.path.abspath(frontend)
raw = open(doc_path, encoding="utf-8").read()
try:
    doc = json.loads(raw)
except ValueError:
    doc = None
def well_shaped(d):
    return (
        isinstance(d, dict)
        and bool(d)
        and all(
            isinstance(v, list)
            and all(isinstance(p, dict) and isinstance(p.get("name"), str) for p in v)
            for v in d.values()
        )
    )
if rc != "0" or not well_shaped(doc):
    if isinstance(doc, dict) and isinstance(doc.get("error"), dict):
        what = f"an error object ({doc['error'].get('code')}: {doc['error'].get('message')})"
    elif doc is None:
        what = f"no JSON ({raw.strip()[:160]!r})"
    elif doc == {}:
        what = "an empty mapping"
    elif well_shaped(doc):
        what = "a licence document, from a pnpm that exited non-zero — neither answer is believed"
    else:
        what = f"a {type(doc).__name__} that is not a licence → packages mapping"
    print(
        f"!! SUPPLY CHAIN UNPROVEN — pnpm licenses list (exit {rc}) did not answer the asked-for "
        f"shape: {what}. No frontend licence was judged.",
        file=sys.stderr,
    )
    sys.exit(2)
def manifest_path(name, version, reported):
    candidates = []
    if reported:
        candidates.append(os.path.join(reported, "package.json"))
        rel = os.path.relpath(reported, root)
        if not rel.startswith(".."):
            candidates.append(os.path.join(root, "node_modules", ".pnpm", rel, "package.json"))
    store = name.replace("/", "+") + "@" + version
    store_path = os.path.join(root, "node_modules", ".pnpm", store, "node_modules", name)
    candidates.append(os.path.join(store_path, "package.json"))
    return next((c for c in candidates if os.path.isfile(c)), None)
def declared(manifest):
    lic = manifest.get("license")
    if isinstance(lic, dict):
        lic = lic.get("type")
    if isinstance(lic, str) and lic.strip():
        return lic.strip()
    many = manifest.get("licenses")
    if isinstance(many, list):
        names = [m.get("type") if isinstance(m, dict) else m for m in many]
        names = [n.strip() for n in names if isinstance(n, str) and n.strip()]
        if names:
            return names[0] if len(names) == 1 else "(" + " OR ".join(names) + ")"
    return None
SEE = re.compile(r"^see licen[cs]e in\s+(.+)$", re.IGNORECASE)
listed = read = 0
unread, bad, unknown = [], [], []
for licence, packages in doc.items():
    for pkg in packages:
        versions = [str(v) for v in pkg.get("versions") or []] or ["?"]
        paths = [str(p) for p in pkg.get("paths") or []]
        for index, version in enumerate(versions):
            listed += 1
            who = f"{pkg['name']}@{version}"
            path = manifest_path(pkg["name"], version, paths[index] if index < len(paths) else "")
            if path is None:
                unread.append(f"{who} (no manifest in the virtual store)")
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    manifest = json.load(fh)
            except (OSError, ValueError) as exc:
                unread.append(f"{who} ({os.path.relpath(path)}: {type(exc).__name__})")
                continue
            own = declared(manifest) if isinstance(manifest, dict) else None
            see = SEE.match(own or "")
            if see:
                named = os.path.join(os.path.dirname(os.path.relpath(path)), see.group(1).strip())
                unread.append(
                    f"{who} (its manifest says SEE LICENSE IN — unjudgeable by name; the terms "
                    f"are in {named})"
                )
                continue
            read += 1
            if banned(licence):
                bad.append(f"{pkg['name']} ({licence})")
            elif own and banned(own):
                bad.append(f"{pkg['name']} ({own} — the manifest's answer; pnpm listed {licence})")
            if own is None or licence.upper() == "UNKNOWN":
                unknown.append(f"{who} (listed {licence}, manifest {own or 'no licence field'})")
print(f"frontend licenses: {listed} listed · {read} read · {len(unread)} unread")
for who in unknown:
    print(f"  licence UNKNOWN, printed and counted, not a red: {who}")
if bad:
    print("copyleft dependencies found:", ", ".join(bad))
if unread:
    print(
        f"!! SUPPLY CHAIN UNPROVEN — {len(unread)} frontend package(s) could not be read back, "
        "and a run is never clean over an unread package:",
        file=sys.stderr,
    )
    for who in unread:
        print(f"   {who}", file=sys.stderr)
    sys.exit(2)
if bad:
    sys.exit(1)
print(f"{py_sentence} · frontend licenses clean ({listed} packages)")
"""
)

#: A judge reads one attempt (exit, stdout, stderr) and answers its verdict word.
Judge = Callable[["Ctx", int, str, str, Path], str]


def unproven(sentence: str) -> int:
    """`!! SUPPLY CHAIN UNPROVEN — <sentence>` on stderr; 2."""
    say(f"!! SUPPLY CHAIN UNPROVEN — {sentence}")
    return 2


def _flush() -> None:
    sys.stdout.flush()
    sys.stderr.flush()


def _env(ctx: Ctx, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(ctx.env)
    env.update(extra or {})
    return env


def network_failure(text: str, finding: re.Pattern[str]) -> bool:
    """The network's shape AND no finding (`supply_chain_network_failure`)."""
    return not finding.search(text) and bool(NETWORK.search(text))


def reader(ctx: Ctx, what: str, program: str, *args: str, capture: bool = False) -> tuple[int, str]:
    """`program` under `uv run python -c` behind the guard; its exit and, if captured, stdout."""
    _flush()
    with tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as out:
        try:
            rc = subprocess.run(
                ["uv", "run", "python", "-c", GUARD + program, *args],
                cwd=ctx.root,
                env=_env(ctx, {"SUPPLY_CHAIN_READER": what}),
                stdout=out if capture else None,
                stderr=err,
            ).returncode
        except OSError as exc:
            return unproven(f"{what} could not run ({exc}); nothing was judged"), ""
        err.seek(0)
        out.seek(0)
        sys.stderr.write(err.read().decode(errors="replace"))
        sys.stderr.flush()
        return rc, out.read().decode(errors="replace")


def judge_pip_audit(ctx: Ctx, rc: int, out: str, err: str, out_path: Path) -> str:
    """pip-audit's answer from its text: a table is a finding, the network's shape a retry."""
    text = out + err
    sys.stdout.write(text)
    if rc == 0:
        return "clean"
    if network_failure(text, PIP_FINDING):
        return "network"
    return "finding" if PIP_FINDING.search(text) else "other"


def judge_pnpm_install(ctx: Ctx, rc: int, out: str, err: str, out_path: Path) -> str:
    """The licence read's own install: an unsatisfied lockfile is a finding."""
    if rc == 0:
        return "clean"
    text = out + err
    sys.stdout.write(text)
    if network_failure(text, PNPM_INSTALL_FINDING):
        return "network"
    return "finding" if PNPM_INSTALL_FINDING.search(text) else "other"


def judge_pnpm_audit(ctx: Ctx, rc: int, out: str, err: str, out_path: Path) -> str:
    """`pnpm audit --json` read as a report first, as text second."""
    r, _ = reader(ctx, "the pnpm audit reader", PNPM_AUDIT, str(out_path), AUDIT_LEVEL)
    sys.stdout.write(err)
    if r == 0:
        if rc == 0:
            return "clean"
        unproven(
            f"pnpm audit exited {rc} over a report with nothing at {AUDIT_LEVEL} or above; the "
            f"two answers disagree, so neither is believed"
        )
        return "unread"
    if r == 1:
        return "finding"
    if r == 2:
        return "unread"
    if r == 4:
        if rc in (0, 1):
            return "clean"
        unproven(
            f"pnpm audit exited {rc} over a report whose every advisory was accepted; nothing "
            f"was judged"
        )
        return "unread"
    if r == 3:
        text = out + err
        if network_failure(text, PNPM_FINDING):
            return "network"
        if PNPM_FINDING.search(text):
            sys.stdout.write(text)
            return "finding"
        sys.stdout.write(out)
        unproven(
            f"pnpm audit (exit {rc}) printed no audit report and no network failure; nothing "
            f"was judged"
        )
        return "unread"
    unproven(f"the pnpm audit reader could not run (exit {r}); nothing was judged")
    return "unread"


def twice(
    ctx: Ctx, tool: str, source: str, judge: Judge, argv: Sequence[str], cwd: Path | None = None
) -> int:
    """The one retry loop: 0 clean · 1 a finding · 2 could-not-look · else the command's exit."""
    rc = 0
    for attempt in (1, 2):
        with tempfile.NamedTemporaryFile(prefix="djb-supply-chain.", delete=False) as handle:
            out_path = Path(handle.name)
        try:
            _flush()
            with out_path.open("wb") as out, tempfile.TemporaryFile() as err:
                try:
                    rc = subprocess.run(
                        list(argv), cwd=cwd or ctx.root, env=_env(ctx), stdout=out, stderr=err
                    ).returncode
                except OSError as exc:
                    err.write(f"{argv[0]} could not be started: {exc}\n".encode())
                    rc = 127
                err.seek(0)
                err_text = err.read().decode(errors="replace")
            verdict = judge(ctx, rc, out_path.read_text(errors="replace"), err_text, out_path)
            sys.stdout.flush()
        finally:
            out_path.unlink()
        if verdict == "clean":
            return 0
        if verdict == "finding":
            return 1
        if verdict == "unread":
            return 2
        if verdict != "network":
            return rc
        if attempt == 1:
            print(f"  {tool} failed on the NETWORK, not on a finding — retrying once.", flush=True)
    say(
        f"!! SUPPLY CHAIN UNPROVEN — {tool} could not reach {source}",
        "   on either attempt: a NETWORK failure, not a vulnerability report. This",
        "   tree's dependencies were not judged, so nothing here is a finding and",
        "   nothing here is a pass. Re-run when the network is back.",
    )
    return 2


def policy_pair(ctx: Ctx) -> int:
    """The licence and advisory policy judge their own canary pairs first; anything else is 2."""
    rc, _ = reader(ctx, "the licence policy's canary pair", POLICY_PAIR)
    if rc in (0, 2):
        return rc
    return unproven(
        f"the licence policy's canary pair could not run (exit {rc}); no licence can be judged"
    )


def pnpm(ctx: Ctx) -> str:
    """The pnpm this leg runs: `FE_PNPM`, else `pnpm`."""
    return ctx.env.get("FE_PNPM") or "pnpm"


def frontend_dir(ctx: Ctx) -> str:
    """The frontend directory: `FE_FRONTEND_DIR`, else `frontend`."""
    return ctx.env.get("FE_FRONTEND_DIR") or "frontend"


def frontend_audit(ctx: Ctx) -> tuple[int, str]:
    """`pnpm audit` over the frontend lock; the directory measured, empty when there is none."""
    folder = frontend_dir(ctx)
    if not (ctx.root / folder / "pnpm-lock.yaml").is_file():
        print(
            f"supply chain: no {folder}/pnpm-lock.yaml — the frontend half is not measured on "
            f"this tree",
            flush=True,
        )
        return 0, ""
    if shutil.which(pnpm(ctx), path=ctx.env.get("PATH")) is None:
        return (
            unproven(
                f"{folder}/pnpm-lock.yaml is on this tree and no pnpm is on PATH; nothing was "
                f"asserted about the frontend's dependencies"
            ),
            "",
        )
    registry = ctx.env.get("FE_PNPM_AUDIT_REGISTRY")
    extra = ("--registry", registry) if registry else ()
    audit = (pnpm(ctx), "audit", "--audit-level", AUDIT_LEVEL, "--prod=false")
    rc = twice(
        ctx,
        "pnpm audit",
        "its advisory source",
        judge_pnpm_audit,
        (*audit, "--json", *extra),
        ctx.root / folder,
    )
    if rc == 1:
        print("  pnpm's own table, as pnpm prints it (the verdict is the report read above):")
        _flush()
        subprocess.run([*audit, *extra], cwd=ctx.root / folder, env=_env(ctx))
    return rc, folder


def frontend_licences(ctx: Ctx, folder: str, py_sentence: str) -> int:
    """The frontend's installed licences read back from each manifest; 0/1/2."""
    if not folder:
        print(py_sentence, flush=True)
        return 0
    if ctx.env.get("FE_LEG_STATE") == "full":
        print(
            "  frontend install: the fe leg's, earlier in this run (pnpm install "
            "--frozen-lockfile) — the licences below are that installed set",
            flush=True,
        )
    else:
        print(
            "  frontend install: this leg's own (pnpm install --frozen-lockfile --ignore-scripts)"
            f" — the fe leg did not install {folder}/ in this run",
            flush=True,
        )
        install = (
            pnpm(ctx),
            "install",
            "--frozen-lockfile",
            "--ignore-scripts",
            "--reporter=append-only",
        )
        rc = twice(
            ctx, "pnpm install", "its registry", judge_pnpm_install, install, ctx.root / folder
        )
        if rc:
            return rc
    with tempfile.NamedTemporaryFile(prefix="djb-supply-chain-licences.", delete=False) as doc:
        doc_path = Path(doc.name)
    try:
        _flush()
        with doc_path.open("wb") as out, tempfile.TemporaryFile() as err:
            listed = subprocess.run(
                [pnpm(ctx), "licenses", "list", "--json"],
                cwd=ctx.root / folder,
                env=_env(ctx),
                stdout=out,
                stderr=err,
            ).returncode
            err.seek(0)
            sys.stdout.write(err.read().decode(errors="replace"))
        r, _ = reader(
            ctx,
            "the frontend licence reader",
            FRONTEND_LICENCES,
            str(doc_path),
            folder,
            str(listed),
            py_sentence,
        )
    finally:
        doc_path.unlink()
    if r in (0, 1, 2):
        return r
    return unproven(f"the frontend licence reader could not run (exit {r}); nothing was judged")


def secrets(ctx: Ctx) -> int:
    """detect-secrets over every tracked file against the baseline; 0/1/2."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ctx.root, capture_output=True)
    if listed.returncode != 0:
        return unproven("git ls-files could not list this tree; no secret scan ran")
    _flush()
    with tempfile.TemporaryFile() as out:
        rc = subprocess.run(
            ["xargs", "-0", *SECRETS],
            cwd=ctx.root,
            env=_env(ctx),
            input=listed.stdout,
            stdout=out,
            stderr=subprocess.STDOUT,
        ).returncode
        out.seek(0)
        text = out.read().decode(errors="replace")
    sys.stdout.write(text)
    if rc == 0:
        return 0
    if "Potential secrets about to be committed" in text:
        print(
            f"  detect-secrets: a secret beyond .secrets.baseline (the scan's own status was {rc})"
            " — a finding. The road, per line: `# pragma: allowlist secret — <what the literal is"
            " and why it is no secret>` on the line, or remove the literal; the baseline only"
            " shrinks by itself",
            flush=True,
        )
        return 1
    return unproven(
        f"detect-secrets-hook reported no finding and no clean scan (xargs exit {rc}); the "
        f"tree's secrets were not judged"
    )


def run(ctx: Ctx) -> int:
    """Policy pair, pip-audit, pnpm audit, the override trigger, licences, secrets; first non-0."""
    rc = policy_pair(ctx)
    if rc:
        return rc
    rc = twice(ctx, "pip-audit", "its advisory source", judge_pip_audit, PIP_AUDIT)
    if rc:
        return rc
    rc, folder = frontend_audit(ctx)
    if rc:
        return rc
    rc, _ = reader(ctx, "the oauthlib override's trigger", OVERRIDE_TRIGGER)
    if rc:
        return rc
    rc, sentence = reader(ctx, "the Python licence reader", PYTHON_LICENCES, capture=True)
    if rc:
        sys.stdout.write(sentence)
        return rc
    rc = frontend_licences(ctx, folder, sentence.rstrip("\n"))
    if rc:
        return rc
    return secrets(ctx)


LEG = Leg(
    "supply-chain",
    "supply-chain",
    "supply chain: pip-audit, pnpm audit, licenses (no GPL/AGPL/SSPL) for both, detect-secrets "
    "over the WHOLE tree vs baseline (the --loop copy sees only the active rung's changed files)",
    run,
    None,
    frozenset({"full"}),
    ARGV,
)
