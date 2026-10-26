"""The supply-chain leg's halves, one by one, against scratch worlds and the real readers."""

# narrowed: case_the_policy_pair_holds — less check.sh's call order (test_legs_supply_chain.py)
# narrowed: case_a_manifest_missing_from_the_store_is_unread — the cause is the leg's stderr
# narrowed: case_a_wrong_shaped_licence_document_is_unproven — the cause is the leg's stderr
# narrowed: case_a_crashing_licence_reader_is_unproven_never_a_finding — the cause is stderr
# narrowed: case_pip_licenses_failing_is_unproven_with_its_cause — the cause is the leg's stderr
# narrowed: case_the_advisory_pair_holds — the cause is the leg's stderr
# narrowed: case_a_post_dated_exception_is_enforcement_broken — the cause is the leg's stderr
# does-not-cover: pip-audit against a live advisory source — the frontend half drives the network.
# does-not-cover: a licence pnpm lists under a name the policy has never seen spelled.
# does-not-cover: the registry's answer itself — the advisory-bearing case reads today's.

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import registry as R
from quality.djb.legs import supply_chain as sc
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "scripts/supply_chain_policy.py", ".secrets.baseline", "frontend/pnpm-lock.yaml"
)

ROOT = Path(__file__).resolve().parents[2]
POLICY = (ROOT / "scripts/supply_chain_policy.py").read_text()
PY_SENTENCE = "licenses clean (the Python half's sentence)"
SHIM = """#!/usr/bin/env bash
case "${1:-}" in
install) exit 0 ;;
audit) cat "$SHIM_AUDIT"; exit "${SHIM_AUDIT_RC:-0}" ;;
licenses) cat "$SHIM_LICENCES"; exit "${SHIM_LICENCES_RC:-0}" ;;
*) echo "pnpm shim: an unexpected question: $*" >&2; exit 97 ;;
esac
"""
PACKAGE = {
    "name": "supply-chain-fixture",
    "private": True,
    "version": "0.0.0",
    "dependencies": {"brace-expansion": "1.1.18"},
}
LOCK = """lockfileVersion: '9.0'

settings:
  autoInstallPeers: true
  excludeLinksFromLockfile: false

importers:

  .:
    dependencies:
      brace-expansion:
        specifier: 1.1.18
        version: 1.1.18

packages:

  balanced-match@1.0.2:
    resolution: {integrity: sha512-3oSeUO0TMV67hN1AmbXsK4yaqU7tjiHlbxRDZOpH0KW9+CeX4bRAaX0Anxt0tx2MrpRpWwQaPwIlISEJhYU5Pw==}

  brace-expansion@1.1.18:
    resolution: {integrity: sha512-Edep/X9fGqVNmzKBVsDYIOtD+z1tuezV70LBjdCst9Tqu76lsnvRiZ6oTic1n+/BIwX6QDGAO94PN4N2SADvtw==}

  concat-map@0.0.1:
    resolution: {integrity: sha512-/Srv4dswyQNBfohGpz9o6Yb3Gz3SrUDqBH5rTuhGR7ahtlbYKnVxw2bCFMRljaA7EXHaXZ8wsHdodFvbkhKmqg==}

snapshots:

  balanced-match@1.0.2: {}

  brace-expansion@1.1.18:
    dependencies:
      balanced-match: 1.0.2
      concat-map: 0.0.1

  concat-map@0.0.1: {}
"""  # noqa: E501
CLEAN_AUDIT = {
    "actions": [],
    "advisories": {},
    "muted": [],
    "metadata": {
        "vulnerabilities": {"info": 0, "low": 0, "moderate": 0, "high": 0, "critical": 0},
        "dependencies": 1,
        "devDependencies": 0,
        "optionalDependencies": 0,
        "totalDependencies": 1,
    },
}
GHSA = "GHSA-vfj7-8cjw-p6xm"
BRACES_PATH = ".>eslint-config-next>@next/eslint-plugin-next>fast-glob>micromatch>braces"
BRACES = json.dumps(
    {
        "actions": [
            {
                "action": "review",
                "module": "braces",
                "resolves": [
                    {
                        "id": 1240992,
                        "path": BRACES_PATH,
                        "dev": False,
                        "bundled": False,
                        "optional": False,
                    }
                ],
            }
        ],
        "advisories": {
            "1240992": {
                "findings": [{"version": "3.0.3", "paths": [BRACES_PATH]}],
                "found_by": None,
                "deleted": None,
                "created": "2026-09-18T18:31:41.000Z",
                "id": 1240992,
                "npm_advisory_id": None,
                "reported_by": None,
                "title": "braces vulnerable to stack-exhaustion denial of service through"
                " deeply nested patterns",
                "metadata": None,
                "cves": ["CVE-2026-93687"],
                "access": "public",
                "severity": "high",
                "module_name": "braces",
                "vulnerable_versions": "<=3.0.3",
                "github_advisory_id": GHSA,
                "recommendation": "None",
                "patched_versions": "<0.0.0",
                "updated": "2026-10-02T22:36:34.000Z",
                "cvss": {
                    "score": 7.5,
                    "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H",
                },
                "cwe": ["CWE-674"],
                "url": f"https://github.com/advisories/{GHSA}",
            }
        },
        "muted": [],
        "metadata": {
            "vulnerabilities": {"info": 0, "low": 0, "moderate": 0, "high": 1, "critical": 0},
            "dependencies": 528,
            "devDependencies": 0,
            "optionalDependencies": 0,
            "totalDependencies": 528,
        },
    }
)

Half = Callable[..., tuple[int, str, str]]


@pytest.fixture
def half(capfd: pytest.CaptureFixture[str]) -> Half:
    """Run one half with this process's environment plus `env`; its exit, stdout and stderr."""

    def run(body: Callable[[R.Ctx], int], root: Path = ROOT, **env: str) -> tuple[int, str, str]:
        capfd.readouterr()
        rc = body(R.Ctx(root, "full", {**os.environ, **env}))
        out, err = capfd.readouterr()
        return rc, out, err

    return run


def both_frontend_halves(ctx: R.Ctx) -> int:
    """The audit, then the licences with the Python half's sentence handed in."""
    rc, folder = sc.frontend_audit(ctx)
    return rc or sc.frontend_licences(ctx, folder, PY_SENTENCE)


def audit_only(ctx: R.Ctx) -> int:
    return sc.frontend_audit(ctx)[0]


@pytest.fixture
def pnpm(stub_path: StubPath) -> str:
    """The pnpm shim: install succeeds, audit and licenses print the planted documents."""
    return str(stub_path.plant("pnpm", SHIM))


@pytest.fixture
def frontend(scratch: Path) -> Callable[[str], Path]:
    """A frontend directory carrying the brace-expansion lock."""

    def build(name: str) -> Path:
        folder = scratch / name
        folder.mkdir()
        (folder / "package.json").write_text(json.dumps(PACKAGE, indent=2) + "\n")
        (folder / "pnpm-lock.yaml").write_text(LOCK)
        return folder

    return build


@pytest.fixture
def document(scratch: Path) -> Callable[[str, str], str]:
    def write(name: str, body: str) -> str:
        (scratch / name).write_text(body + "\n")
        return str(scratch / name)

    return write


def policy_with(scratch: Path, name: str, tail: str) -> str:
    """A copy of the licence policy with `tail` appended, as a policy directory."""
    folder = scratch / name
    folder.mkdir()
    (folder / "supply_chain_policy.py").write_text(POLICY + tail)
    return str(folder)


def exception_line(declared: str, until: str) -> str:
    return (
        f'\n\nADVISORY_EXCEPTIONS = (\n    AdvisoryException(ghsa="{GHSA}", why="planted",'
        f' paths=("{BRACES_PATH}",), declared=date({declared}), until=date({until})),\n)\n'
    )


# --- the policy pairs ----------------------------------------------------------------


def test_the_policy_pair_holds(half: Half, scratch: Path) -> None:
    rc, out, err = half(sc.policy_pair)
    assert rc == 0, err
    assert "the canary pair holds" in out + err
    for way, body in (("everything", "True"), ("nothing", "False")):
        tail = f"\n\ndef banned(licence: str) -> bool:\n    return {body}\n"
        planted = policy_with(scratch, f"policy-{way}", tail)
        rc, out, err = half(sc.policy_pair, DJB_SUPPLY_CHAIN_POLICY_DIR=planted)
        assert rc == 2, f"a policy that bans {way} was not enforcement broken"
        assert "SUPPLY CHAIN ENFORCEMENT BROKEN" in err
        said = out + err
        assert "must be accepted and was refused" in said or "must be refused and was accepted" in (
            said
        )


def test_the_advisory_pair_holds(half: Half, scratch: Path) -> None:
    rc, out, err = half(sc.policy_pair)
    assert rc == 0
    assert (
        "advisory policy: the canary pair holds (5 refused · 2 accepted; exceptions declared: 1)"
    ) in out + err
    judge = "\n\ndef judge_advisory(advisory, today, exceptions=None):\n    return {}, 'planted'\n"
    for way, tail in (
        ("accept", judge.format("True")),
        ("refuse", judge.format("False")),
        (
            "window",
            '\n\nADVISORY_EXCEPTIONS = (AdvisoryException(ghsa="GHSA-2222-3333-4444",'
            ' why="planted", paths=("a",), declared=date(2026, 1, 1),'
            " until=date(2026, 6, 1)),)\n",
        ),
    ):
        planted = policy_with(scratch, f"advisory-{way}", tail)
        rc, out, err = half(sc.policy_pair, DJB_SUPPLY_CHAIN_POLICY_DIR=planted)
        said = out + err
        assert rc == 2, f"an advisory policy broken ({way}) was not refused"
        assert "SUPPLY CHAIN ENFORCEMENT BROKEN" in err
        assert any(
            one in said
            for one in (
                "advisory must be accepted and was refused",
                "advisory must be refused and was accepted",
                "stands 151 days, outside 1..60",
            )
        ), said


def test_a_post_dated_exception_is_enforcement_broken(half: Half, scratch: Path) -> None:
    planted = policy_with(scratch, "advisory-future", exception_line("2099, 6, 1", "2099, 7, 30"))
    rc, out, err = half(sc.policy_pair, DJB_SUPPLY_CHAIN_POLICY_DIR=planted)
    assert rc == 2
    assert "SUPPLY CHAIN ENFORCEMENT BROKEN" in err
    assert f"{GHSA} is declared in the future (2099-06-01)" in out + err


# --- the frontend audit ----------------------------------------------------------------


def test_no_frontend_tree_is_not_measured_and_says_so(half: Half, scratch: Path) -> None:
    rc, out, err = half(
        both_frontend_halves, FE_FRONTEND_DIR=str(scratch / "no-such"), FE_PNPM="/nonexistent"
    )
    assert rc == 0
    assert "the frontend half is not measured on this tree" in out
    assert PY_SENTENCE in out
    assert "frontend licenses" not in out + err


def test_no_pnpm_with_a_lock_is_unproven(half: Half, frontend: Callable[[str], Path]) -> None:
    rc, out, err = half(audit_only, FE_FRONTEND_DIR=str(frontend("nopnpm")), FE_PNPM="/nonexistent")
    assert rc == 2
    assert (
        "is on this tree and no pnpm is on PATH; nothing was asserted about the frontend's"
        " dependencies"
    ) in err


def test_a_count_only_audit_report_is_never_clean(
    half: Half, frontend: Callable[[str], Path], pnpm: str, document: Callable[..., str]
) -> None:
    counted = json.loads(json.dumps(CLEAN_AUDIT))
    counted["metadata"]["vulnerabilities"]["high"] = 2
    rc, out, err = half(
        audit_only,
        FE_FRONTEND_DIR=str(frontend("countonly")),
        FE_PNPM=pnpm,
        SHIM_AUDIT=document("count.json", json.dumps(counted)),
        SHIM_AUDIT_RC="1",
    )
    assert rc == 1
    assert "advisories reported by count and not by record: high=" in out + err


@pytest.fixture
def braces(
    half: Half, frontend: Callable[[str], Path], pnpm: str, document: Callable[..., str]
) -> Callable[..., tuple[int, str]]:
    """The audit over the CI's braces report, rewritten by `edits`; its exit and its text."""

    count = 0

    def run(*edits: tuple[str, str], **env: str) -> tuple[int, str]:
        nonlocal count
        count += 1
        report = BRACES
        for old, new in edits:
            assert old in report, f"the edit's anchor is not in the report: {old!r}"
            report = report.replace(old, new)
        rc, out, err = half(
            audit_only,
            FE_FRONTEND_DIR=str(frontend(f"braces-{count}")),
            FE_PNPM=pnpm,
            SHIM_AUDIT=document(f"audit-braces-{count}.json", report),
            SHIM_AUDIT_RC="1",
            **env,
        )
        return rc, out + err

    return run


def test_the_ci_braces_report_is_accepted_by_its_declared_exception(
    braces: Callable[..., tuple[int, str]],
) -> None:
    rc, said = braces()
    assert rc == 0, said
    assert f"accepted: {GHSA} — " in said
    assert "ends when a patched range exists)" in said
    assert "1 accepted by declared exception" in said
    assert "one per record" not in said


def test_an_unlisted_advisory_is_refused(braces: Callable[..., tuple[int, str]]) -> None:
    rc, said = braces((GHSA, "GHSA-9999-9999-9999"))
    assert rc == 1
    assert "braces@3.0.3" in said
    assert "GHSA-9999-9999-9999 is not a declared exception" in said
    assert "accepted:" not in said


def test_a_listed_advisory_with_a_patched_range_is_refused(
    braces: Callable[..., tuple[int, str]],
) -> None:
    rc, said = braces(('"patched_versions": "<0.0.0"', '"patched_versions": ">=3.0.4"'))
    assert rc == 1
    assert f"exception ended: {GHSA} — a patched range exists (>=3.0.4); move braces to it" in said
    assert "accepted:" not in said


def test_a_listed_advisory_on_an_undeclared_path_is_refused(
    braces: Callable[..., tuple[int, str]],
) -> None:
    rc, said = braces((BRACES_PATH, ".>next>runtime>braces"))
    assert rc == 1
    assert f"exception does not cover: {GHSA} reached on .>next>runtime>braces" in said


def test_a_listed_advisory_past_its_until_is_refused(
    braces: Callable[..., tuple[int, str]], scratch: Path
) -> None:
    planted = policy_with(scratch, "policy-expired", exception_line("2026, 1, 1", "2026, 2, 1"))
    rc, said = braces(DJB_SUPPLY_CHAIN_POLICY_DIR=planted)
    assert rc == 1
    assert f"exception ended: {GHSA} — its until 2026-02-01 has passed" in said
    assert "accepted:" not in said


def test_an_accepted_advisory_does_not_waive_an_unexplained_count(
    braces: Callable[..., tuple[int, str]],
) -> None:
    rc, said = braces(('"high": 1', '"high": 2'))
    assert rc == 1
    assert f"accepted: {GHSA}" in said
    assert "advisories reported by count and not by record: high=1" in said


# --- the frontend licences --------------------------------------------------------------


@pytest.fixture
def licences(
    half: Half, scratch: Path, pnpm: str, document: Callable[..., str]
) -> Callable[..., tuple[int, str, str]]:
    """One package in a scratch store, pnpm listing `listed`, its manifest saying `manifest`."""
    clean = document("clean-audit.json", json.dumps(CLEAN_AUDIT))

    def run(
        name: str, listed: str, manifest: str, doc: str = "", rc: str = "0", store: bool = True
    ) -> tuple[int, str, str]:
        folder = scratch / name
        folder.mkdir()
        (folder / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
        if store:
            home = folder / f"node_modules/.pnpm/{name}@1.0.0/node_modules/{name}"
            home.mkdir(parents=True)
            (home / "package.json").write_text(
                f'{{"name": "{name}", "version": "1.0.0", "license": {manifest}}}\n'
            )
        entry = {
            "name": name,
            "versions": ["1.0.0"],
            "paths": [f"{folder}/{name}@1.0.0/node_modules/{name}"],
            "license": listed,
        }
        (folder / "licences.json").write_text(doc or json.dumps({listed: [entry]}) + "\n")
        return half(
            both_frontend_halves,
            FE_FRONTEND_DIR=str(folder),
            FE_PNPM=pnpm,
            SHIM_AUDIT=clean,
            SHIM_LICENCES=str(folder / "licences.json"),
            SHIM_LICENCES_RC=rc,
        )

    return run


def test_a_copyleft_frontend_dependency_is_refused(
    licences: Callable[..., tuple[int, str, str]],
) -> None:
    rc, out, err = licences("agpl-fixture", "AGPL-3.0", '"AGPL-3.0"')
    assert rc == 1
    assert "copyleft dependencies found: agpl-fixture (AGPL-3.0)" in out + err
    rc, out, err = licences("mit-fixture", "MIT", '"MIT"')
    assert rc == 0, err
    assert "copyleft dependencies found" not in out + err
    assert "· frontend licenses clean (" in out
    assert PY_SENTENCE in out


def test_a_see_license_in_manifest_is_unread_never_clean(
    licences: Callable[..., tuple[int, str, str]],
) -> None:
    rc, out, err = licences("see-fixture", "MIT", '"SEE LICENSE IN LICENSE.txt"')
    said = out + err
    assert rc == 2
    for one in ("see-fixture@1.0.0", "unjudgeable by name", "LICENSE.txt"):
        assert one in said
    assert "frontend licenses clean" not in said


def test_the_manifest_answer_is_judged_beside_the_listed_one(
    licences: Callable[..., tuple[int, str, str]],
) -> None:
    rc, out, err = licences("sniffed-fixture", "BSD", '"AGPL-3.0"')
    assert rc == 1
    assert "sniffed-fixture (AGPL-3.0 — the manifest's answer; pnpm listed BSD)" in out + err


def test_a_manifest_missing_from_the_store_is_unread(
    licences: Callable[..., tuple[int, str, str]],
) -> None:
    rc, out, err = licences("missing-fixture", "MIT", '"MIT"', store=False)
    assert rc == 2
    assert "missing-fixture@1.0.0 (no manifest in the virtual store)" in out + err
    assert "frontend licenses clean" not in out + err
    assert "could not be read back" in err


def test_a_wrong_shaped_licence_document_is_unproven(
    licences: Callable[..., tuple[int, str, str]],
) -> None:
    planted = '{"error": {"code": "ERR_PNPM_PLANTED", "message": "a planted error object"}}'
    rc, out, err = licences("shape-fixture", "MIT", '"MIT"', doc=planted, rc="1")
    assert rc == 2
    assert "did not answer the asked-for shape" in err
    assert "ERR_PNPM_PLANTED" in out + err


def test_a_crashing_licence_reader_is_unproven_never_a_finding(
    licences: Callable[..., tuple[int, str, str]],
) -> None:
    planted = '{"MIT": [{"name": "crash-fixture", "versions": 5, "paths": [], "license": "MIT"}]}'
    rc, out, err = licences("crash-fixture", "MIT", '"MIT"', doc=planted)
    assert rc == 2
    assert "SUPPLY CHAIN UNPROVEN — the frontend licence reader raised TypeError" in err
    assert "copyleft dependencies found" not in out + err


def test_pip_licenses_failing_is_unproven_with_its_cause(half: Half, stub_path: StubPath) -> None:
    real = shutil.which("uv")
    assert real, "no uv on PATH — the leg's readers run through it"
    stub_path.plant(
        "uv",
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = run ] && [ "${2:-}" = pip-licenses ]; then\n'
        '    echo "uv shim: pip-licenses refused on purpose" >&2\n'
        "    exit 3\n"
        "fi\n"
        f'exec "{real}" "$@"\n',
    )
    rc, out, err = half(
        lambda ctx: sc.reader(ctx, "the Python licence reader", sc.PYTHON_LICENCES)[0],
        PATH=f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}",
    )
    assert rc == 2
    assert "pip-licenses exited 3" in err
    assert "licenses clean" not in out + err


# --- the whole-tree secret scan ----------------------------------------------------------


@pytest.fixture
def secrets_repo(scratch_repo: Callable[..., Path], half: Half) -> Path:
    """A scratch tree with one clean file and a baseline the real scanner wrote over it."""
    repo = scratch_repo("secrets")
    (repo / "clean.py").write_text("VALUE = 1\n")
    rc, out, _ = half(
        lambda ctx: (
            subprocess.run(
                ["uv", "run", "detect-secrets", "scan", "clean.py"],
                cwd=ctx.root,
                env=dict(ctx.env),
                stdout=(repo / ".secrets.baseline").open("w"),
            ).returncode
        ),
        root=repo,
        UV_PROJECT=str(ROOT),
    )
    assert rc == 0, "could not write a scratch baseline"
    subprocess.run(["git", "-C", str(repo), "add", "clean.py", ".secrets.baseline"], check=True)
    return repo


def test_a_planted_secret_reds_the_secrets_half_with_one(half: Half, secrets_repo: Path) -> None:
    assert half(sc.secrets, root=secrets_repo, UV_PROJECT=str(ROOT))[0] == 0
    word = "pass" + "word"
    (secrets_repo / "planted.py").write_text(f'{word} = "planted-xxxxxxxx-value"\n')
    subprocess.run(["git", "-C", str(secrets_repo), "add", "planted.py"], check=True)
    rc, out, err = half(sc.secrets, root=secrets_repo, UV_PROJECT=str(ROOT))
    assert rc == 1
    assert "planted.py" in out and "a secret beyond .secrets.baseline" in out


def test_a_secrets_scan_with_no_verdict_is_unproven(half: Half, secrets_repo: Path) -> None:
    subprocess.run(
        ["git", "-C", str(secrets_repo), "rm", "-q", "--cached", ".secrets.baseline"], check=True
    )
    (secrets_repo / ".secrets.baseline").unlink()
    rc, out, err = half(sc.secrets, root=secrets_repo, UV_PROJECT=str(ROOT))
    assert rc == 2
    assert "detect-secrets-hook reported no finding and no clean scan" in err


# --- pnpm's own audit, against a network ---------------------------------------------------


def test_a_network_failure_is_unproven_on_both_attempts(
    half: Half, frontend: Callable[[str], Path]
) -> None:
    if shutil.which("pnpm") is None:
        raise CouldNotLook("no pnpm on PATH — this case drives pnpm's own network failure")
    rc, out, err = half(
        audit_only,
        FE_FRONTEND_DIR=str(frontend("unreachable")),
        FE_PNPM_AUDIT_REGISTRY="http://127.0.0.1:9",
        npm_config_fetch_retries="0",
    )
    said = out + err
    assert rc == 2
    assert "pnpm audit failed on the NETWORK, not on a finding — retrying once." in said
    assert "SUPPLY CHAIN UNPROVEN — pnpm audit could not reach its advisory source" in said
    assert "ECONNREFUSED" in said
    assert "one per record" not in said


def test_an_advisory_bearing_lock_reds_the_leg(half: Half, frontend: Callable[[str], Path]) -> None:
    if shutil.which("pnpm") is None:
        raise CouldNotLook("no pnpm on PATH — this case drives pnpm's own audit")
    rc, out, err = half(audit_only, FE_FRONTEND_DIR=str(frontend("advisory")))
    said = out + err
    if rc == 2 and "pnpm audit could not reach its advisory source" in said:
        raise CouldNotLook("the npm registry could not be reached on either attempt")
    assert rc == 1, said
    assert "brace-expansion@1.1.18" in said
    assert "one per record" in said and "pnpm's own table" in said
