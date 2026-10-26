"""`deploy/iam/product_bootstrap.sh`: a product's once-only AWS hand, driven against a stub `aws`.

does-not-cover: whether IAM, ECR or STS answer the way the stub's canned replies do.
does-not-cover: whether the rendered documents grant what CI and the box actually need at run time.
does-not-cover: the GitHub side — the printed `gh variable set` lines are read, never run.
does-not-cover: which OIDC subject spelling GitHub issues; only the rendering of both is read.
does-not-cover: whether GitHub's API answers ids the way the stub `gh` does.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives("deploy/iam/product_bootstrap.sh", "deploy/iam/product-*.json")

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deploy" / "iam" / "product_bootstrap.sh"
IAM = ROOT / "deploy" / "iam"
BASE_PATH = "/usr/bin:/bin"
NAMESPACE = "drivens"
REGION = "us-east-1"
ENV = "staging"
REPO = "acme-owner/acme-product"
# The stub's account: no real account carries it, so a composed string cannot pass as a read one.
ACCOUNT = "111122223333"
# The stub `gh`'s owner and repository ids, and the id-spelled subject prefix they make.
IDS = "42/4242"
TWIN = "repo:acme-owner@42/acme-product@4242:"
SUB = "token.actions.githubusercontent.com:sub"

AWS_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$REC/aws.argv"
MODE="$(cat "$REC/mode")"
[ "$1" = "--region" ] && shift 2
printf '%s %s\n' "${1:-}" "${2:-}" >>"$REC/aws.ops"
arg() {
    local want="$1"
    shift
    while [ "$#" -gt 0 ]; do
        [ "$1" = "$want" ] && { echo "$2"; return; }
        shift
    done
}
missing() { echo "An error occurred (NoSuchEntity) when calling the operation" >&2; exit 254; }
case "$1 $2" in
"sts get-caller-identity") cat "$REC/account" ;;
"iam get-role")
    [ "$MODE" = "exists" ] || missing
    name="$(arg --role-name "$@")"
    case "$*" in
    *AssumeRolePolicyDocument*) cat "$REC/live/trust-$name.json" 2>/dev/null || echo "{}" ;;
    *) echo "arn:aws:iam::$(cat "$REC/account"):role/stub-read/$name" ;;
    esac
    ;;
"iam create-role")
    echo "arn:aws:iam::$(cat "$REC/account"):role/stub-made/$(arg --role-name "$@")"
    ;;
"iam get-role-policy")
    [ "$MODE" = "exists" ] || missing
    live="$REC/live/$(arg --role-name "$@")--$(arg --policy-name "$@").json"
    [ -f "$live" ] || missing
    cat "$live"
    ;;
"iam put-role-policy")
    mkdir -p "$REC/live"
    arg --policy-document "$@" >"$REC/live/$(arg --role-name "$@")--$(arg --policy-name "$@").json"
    ;;
"iam get-instance-profile") [ "$MODE" = "exists" ] || missing ;;
"iam list-open-id-connect-providers")
    if [ "$MODE" = "exists" ]; then
        echo "arn:aws:iam::$(cat "$REC/account"):oidc-provider/token.actions.githubusercontent.com"
    fi
    ;;
"iam create-open-id-connect-provider")
    echo "arn:aws:iam::$(cat "$REC/account"):oidc-provider/token.actions.githubusercontent.com"
    ;;
"ecr describe-repositories")
    [ "$MODE" = "exists" ] || {
        echo "An error occurred (RepositoryNotFoundException) when calling the operation" >&2
        exit 254
    }
    ;;
*) echo "{}" ;;
esac
exit 0
"""

GH_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$REC/gh.argv"
if [ "$(cat "$REC/gh-mode" 2>/dev/null)" = fail ]; then
    echo "HTTP 404: Not Found (https://api.github.com/repos/acme-owner/acme-product)" >&2
    exit 1
fi
cat "$REC/gh-ids"
"""

CREATES = r"^(iam|ecr) (create|put|attach|add|update|tag)-"
DOCS = {
    "box-trust": "product-box-trust.json",
    "box": "product-box-policy.json",
    "box-ecr": "product-box-ecr-policy.json",
    "images-trust": "product-ci-images-trust.json",
    "images": "product-ci-images-policy.json",
    "public-login": "product-ci-ecr-public-login.json",
    "public-push": "product-ci-ecr-public-push.json",
    "deploy-trust": "product-ci-deploy-trust.json",
    "deploy": "product-ci-deploy-policy.json",
}
BOX_ROLE = f"{NAMESPACE}-{ENV}-box"
IMAGES_ROLE = f"{NAMESPACE}-ci-images"
DEPLOY_ROLE = f"{NAMESPACE}-ci-deploy"
# role → ((inline policy name, document key), …) — the runbook's names, one per inline policy.
INLINE = {
    BOX_ROLE: (("djb-box", "box"), ("djb-box-ecr", "box-ecr")),
    IMAGES_ROLE: (
        ("djb-ci-images", "images"),
        ("ecr-public-login", "public-login"),
        ("ecr-public-push", "public-push"),
    ),
    DEPLOY_ROLE: (("djb-ci-deploy", "deploy"),),
}
TRUST = {BOX_ROLE: "box-trust", IMAGES_ROLE: "images-trust", DEPLOY_ROLE: "deploy-trust"}


def rendered(key: str, twins: bool = True) -> str:
    """A tracked document with its seven slots filled and each OIDC subject's id-spelled twin."""
    text = (IAM / DOCS[key]).read_text()
    slots = {"ACCOUNT_ID": ACCOUNT, "REGION": REGION, "NAMESPACE": NAMESPACE, "ENV": ENV}
    for kind in ("MEDIA", "BACKUPS"):
        slots[f"{kind}_BUCKET"] = f"{NAMESPACE}-{ENV}-{ACCOUNT}-{kind.lower()}"
    for slot, value in {**slots, "REPO": REPO}.items():
        text = text.replace("${" + slot + "}", value)
    doc = json.loads(text)
    for statement in doc["Statement"] if twins else ():
        like = statement.get("Condition", {}).get("StringLike", {})
        if SUB in like:
            like[SUB] = [s for c in like[SUB] for s in (c, c.replace(f"repo:{REPO}:", TWIN))]
    return json.dumps(doc)


def subjects(document: str) -> list[str]:
    """The OIDC subject list of a one-statement trust document."""
    return list(json.loads(document)["Statement"][0]["Condition"]["StringLike"][SUB])


@dataclass
class Account:
    """A recording `aws` that answers `fresh` or `exists` from files the case writes."""

    root: Path
    stubs: StubPath

    @property
    def rec(self) -> Path:
        """Where the stub records its argv and reads its answers."""
        return self.root / "rec"

    def answer(self, name: str, value: str) -> None:
        """Plant one answer file under `rec/`."""
        path = self.rec / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if value.endswith("\n") else value + "\n")

    def agree(self) -> None:
        """Every live trust and inline document answers exactly what this tree renders."""
        for role, key in TRUST.items():
            self.answer(f"live/trust-{role}.json", rendered(key))
        for role, pairs in INLINE.items():
            for name, key in pairs:
                self.answer(f"live/{role}--{name}.json", rendered(key))

    def env(self, drop: Sequence[str] = (), **extra: str) -> dict[str, str]:
        """The drive's `env -i` world with every coordinate, less `drop`, plus `extra`."""
        world = {
            "PATH": f"{self.stubs.bin}:{BASE_PATH}",
            "HOME": str(self.root),
            "TMPDIR": str(self.root),
            "REC": str(self.rec),
            "DJB_DEPLOY_NAMESPACE": NAMESPACE,
            "AWS_REGION": REGION,
            "DJB_ENV": ENV,
            "DJB_GITHUB_REPO": REPO,
            **extra,
        }
        return {k: v for k, v in world.items() if k not in drop}

    def run(self, *args: str, drop: Sequence[str] = (), **extra: str) -> tuple[int, str]:
        """The bootstrap once, both streams to a file (the script refuses a pipe)."""
        with tempfile.TemporaryFile() as sink:
            done = subprocess.run(
                ["bash", str(SCRIPT), *args],
                env=self.env(drop, **extra),
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=sink,
                stderr=subprocess.STDOUT,
            )
            sink.seek(0)
            return done.returncode, sink.read().decode(errors="replace")

    def text(self, name: str) -> str:
        """A record's text, empty when nothing was recorded."""
        path = self.rec / name
        return path.read_text() if path.is_file() else ""

    def calls(self, pattern: str) -> list[str]:
        """The recorded argv lines whose `<service> <operation>` matches `pattern`."""
        ops = self.text("aws.ops").splitlines()
        argv = self.text("aws.argv").splitlines()
        return [a for o, a in zip(ops, argv, strict=True) if re.search(pattern, o)]


@pytest.fixture
def account(scratch: Path) -> Account:
    """A fresh account: the recording `aws`, the stub's account id, nothing existing yet."""
    if not SCRIPT.is_file():
        raise CouldNotLook(f"{SCRIPT} is missing — there is nothing to drive")
    if not os.access(ROOT / ".venv" / "bin" / "python", os.X_OK):
        raise CouldNotLook("this checkout has no .venv/bin/python; run ./scripts/setup.sh first")
    root = scratch / "account"
    (root / "bin").mkdir(parents=True)
    stubs = StubPath(root / "bin")
    stubs.plant("aws", AWS_STUB)
    stubs.plant("gh", GH_STUB)
    made = Account(root, stubs)
    made.answer("account", ACCOUNT)
    made.answer("gh-ids", IDS)
    made.answer("mode", "fresh")
    return made


def report(made: Account, out: str) -> str:
    """The run's output and the recorded argv, for a failure message."""
    return f"--- output ---\n{out}\n--- aws argv ---\n{made.text('aws.argv') or '(none)'}"


@pytest.mark.parametrize(
    "missing", ["DJB_DEPLOY_NAMESPACE", "AWS_REGION", "DJB_ENV", "DJB_GITHUB_REPO"]
)
def test_each_missing_coordinate_is_exit_2_before_any_aws_call(
    account: Account, missing: str
) -> None:
    """No coordinate, even under --confirm, is exit 2 naming it, and `aws` is never called."""
    rc, out = account.run("--confirm", drop=(missing,))
    assert rc == 2, f"wanted exit 2 without {missing}, got {rc}\n{report(account, out)}"
    assert missing in out, f"the refusal does not name {missing}\n{out}"
    assert account.text("aws.argv") == "", f"aws was called: {account.text('aws.argv')}"


def test_a_repository_that_is_not_owner_slash_repo_is_refused(account: Account) -> None:
    """`DJB_GITHUB_REPO` is one `<owner>/<repo>`; a wildcard is a trust nobody can read."""
    for bad in ("acme-owner/*", "acme-product", "a/b/c"):
        rc, out = account.run("--confirm", DJB_GITHUB_REPO=bad)
        assert rc == 2 and "DJB_GITHUB_REPO" in out, f"{bad!r}: exit {rc}\n{out}"
    assert account.text("aws.argv") == ""


def test_the_plan_names_every_resource_and_creates_nothing(account: Account) -> None:
    """The bare run prints every name it would make, calls no `aws`, and exits 2."""
    rc, out = account.run()
    assert rc == 2, f"wanted exit 2 without --confirm, got {rc}\n{report(account, out)}"
    assert account.text("aws.argv") == "", "the plan called aws"
    want = (
        f"{NAMESPACE}, region {REGION}, environment {ENV}, repository {REPO}",
        f"role {BOX_ROLE}",
        f"instance profile {BOX_ROLE}",
        f"{NAMESPACE}/djb-web",
        f"{NAMESPACE}/djb-worker",
        f"{NAMESPACE}/djb-frontend",
        "token.actions.githubusercontent.com",
        f"role {IMAGES_ROLE}",
        f"role {DEPLOY_ROLE}",
        f"djb:namespace={NAMESPACE}",
        "--confirm",
    )
    misses = [w for w in want if w not in out]
    for pairs in INLINE.values():
        misses += [name for name, _ in pairs if name not in out]
    assert not misses, f"the plan does not name: {misses}\n{out}"
    sids = [
        s["Sid"]
        for key, file in DOCS.items()
        if not key.endswith("trust")
        for s in json.loads((IAM / file).read_text())["Statement"]
    ]
    assert [s for s in sids if s not in out] == [], "a permission statement is not summarised"


def test_confirm_issues_each_create_exactly_once(account: Account) -> None:
    """A fresh account: three roles, six inline policies, one profile, one provider, three repos."""
    rc, out = account.run("--confirm")
    assert rc == 0, f"the first run exited {rc}\n{report(account, out)}"
    roles = [_flag(c, "--role-name") for c in account.calls("^iam create-role$")]
    assert sorted(roles) == sorted(INLINE), roles
    puts = sorted(
        (_flag(c, "--role-name"), _flag(c, "--policy-name"))
        for c in account.calls("^iam put-role-policy$")
    )
    assert puts == sorted((r, n) for r, pairs in INLINE.items() for n, _ in pairs), puts
    once = {
        "iam create-instance-profile": 1,
        "iam add-role-to-instance-profile": 1,
        "iam create-open-id-connect-provider": 1,
        "ecr create-repository": 3,
    }
    wrong = {k: len(account.calls(f"^{k}$")) for k in once}
    assert wrong == once, f"{wrong}\n{report(account, out)}"
    repos = account.calls("^ecr create-repository$")
    assert all("--image-tag-mutability IMMUTABLE" in r for r in repos), repos
    assert all("scanOnPush=true" in r for r in repos), repos
    assert all(f"--region {REGION}" in a for a in account.text("aws.argv").splitlines())


def test_confirm_sends_the_tracked_documents_rendered(account: Account) -> None:
    """Each trust and inline document reaches AWS with every slot filled and no slot left."""
    account.run("--confirm")
    argv = account.text("aws.argv")
    assert "${" not in argv, "a slot reached AWS unfilled"
    for role, key in TRUST.items():
        made = [c for c in account.calls("^iam create-role$") if f"--role-name {role} " in c]
        assert made and json.dumps(json.loads(rendered(key))) in _docs(made[0]), role
    for role, pairs in INLINE.items():
        for name, key in pairs:
            put = [
                c
                for c in account.calls("^iam put-role-policy$")
                if f"--role-name {role} " in c and f"--policy-name {name} " in c
            ]
            assert put and json.dumps(json.loads(rendered(key))) in _docs(put[0]), (role, name)
    assert subjects(rendered("images-trust")) == [
        f"repo:{REPO}:ref:refs/heads/main",
        f"{TWIN}ref:refs/heads/main",
        f"repo:{REPO}:pull_request",
        f"{TWIN}pull_request",
    ]
    assert subjects(rendered("deploy-trust")) == [
        f"repo:{REPO}:ref:refs/heads/main",
        f"{TWIN}ref:refs/heads/main",
    ]


def _flag(argv_line: str, flag: str) -> str:
    """The word after `flag` in one recorded argv line."""
    found = re.search(rf"{flag} (\S+)", argv_line)
    assert found, f"{flag} is not in {argv_line!r}"
    return found[1]


def _docs(argv_line: str) -> str:
    """Every JSON object in one argv line, re-serialised canonically and joined."""
    found, decoder, i = [], json.JSONDecoder(), 0
    while (i := argv_line.find("{", i)) != -1:
        try:
            value, end = decoder.raw_decode(argv_line, i)
        except ValueError:
            i += 1
            continue
        found.append(json.dumps(value))
        i = end
    return "\n".join(found)


def test_a_second_confirm_creates_nothing(account: Account) -> None:
    """Everything existing and agreeing: exit 0, no creating call, and each says `exists`."""
    account.answer("mode", "exists")
    account.agree()
    rc, out = account.run("--confirm")
    assert rc == 0, f"the second run exited {rc}\n{report(account, out)}"
    assert account.calls(CREATES) == [], report(account, out)
    assert out.count("exists") >= 6 and out.count("up to date") == 9, out


def test_a_drifted_document_is_printed_and_never_applied(account: Account) -> None:
    """A live document that differs prints the one command to publish it and runs none."""
    account.answer("mode", "exists")
    account.agree()
    account.answer(f"live/{IMAGES_ROLE}--djb-ci-images.json", '{"Version": "2012-10-17"}')
    account.answer(f"live/trust-{DEPLOY_ROLE}.json", '{"Version": "2012-10-17"}')
    rc, out = account.run("--confirm")
    assert rc == 0, report(account, out)
    assert account.calls(CREATES) == [], report(account, out)
    assert f"put-role-policy --role-name {IMAGES_ROLE} --policy-name djb-ci-images" in out, out
    assert f"update-assume-role-policy --role-name {DEPLOY_ROLE}" in out, out


def test_the_printed_variable_lines_carry_the_stubs_arns(account: Account) -> None:
    """The four `gh variable set` lines name the repository and what AWS answered."""
    rc, out = account.run("--confirm")
    assert rc == 0, report(account, out)
    lines = [x.strip() for x in out.splitlines() if x.strip().startswith("gh variable set")]
    want = [
        f"gh variable set AWS_ECR_ROLE_ARN --repo {REPO} --body "
        f"arn:aws:iam::{ACCOUNT}:role/stub-made/{IMAGES_ROLE}",
        f"gh variable set DJB_IMAGE_REGISTRY --repo {REPO} --body "
        f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{NAMESPACE}",
        f"gh variable set AWS_REGION --repo {REPO} --body {REGION}",
        f"gh variable set DJB_DEPLOY_NAMESPACE --repo {REPO} --body {NAMESPACE}",
    ]
    assert lines == want, out
    account.answer("mode", "exists")
    account.agree()
    _, again = account.run("--confirm")
    assert f"--body arn:aws:iam::{ACCOUNT}:role/stub-read/{IMAGES_ROLE}" in again, again
    assert f"arn:aws:iam::{ACCOUNT}:role/stub-read/{DEPLOY_ROLE}" in again, again


def test_an_existing_oidc_provider_is_reused(account: Account) -> None:
    """One provider per account: found, it is named and no second one is created."""
    account.answer("mode", "exists")
    account.agree()
    _, out = account.run("--confirm")
    assert account.calls("^iam create-open-id-connect-provider$") == []
    assert "oidc-provider/token.actions.githubusercontent.com exists" in out, out


def test_the_plan_carries_both_subject_spellings_from_the_ids_gh_answered(
    account: Account,
) -> None:
    """The plan reads the ids once from `gh` and prints every subject of both CI roles."""
    rc, out = account.run()
    assert rc == 2 and account.text("aws.argv") == "", report(account, out)
    assert account.text("gh.argv").splitlines() == [
        f'api repos/{REPO} --jq "\\(.owner.id)/\\(.id)"'
    ], account.text("gh.argv")
    want = subjects(rendered("images-trust")) + subjects(rendered("deploy-trust"))
    assert [s for s in want if f"         {s}" not in out] == [], out
    assert f"ids {IDS}" in out, out


@pytest.mark.parametrize("how", ["fails", "absent", "garbled"])
def test_a_gh_that_cannot_answer_refuses_the_apply(account: Account, how: str) -> None:
    """No ids from `gh`: the plan says so and `--confirm` is exit 2 with no `aws` call."""
    if how == "fails":
        account.answer("gh-mode", "fail")
    elif how == "absent":
        account.stubs.remove("gh")
    else:
        account.answer("gh-ids", "Not Found")
    rc, out = account.run("--confirm")
    assert rc == 2, f"{how}: wanted exit 2, got {rc}\n{report(account, out)}"
    assert "OIDC trust: REFUSED" in out and "DJB_GITHUB_REPO_IDS" in out, out
    assert account.text("aws.argv") == "", f"aws was called: {account.text('aws.argv')}"


def test_a_found_role_missing_the_id_spelled_subjects_gains_them(account: Account) -> None:
    """A CI role made before both spellings: one update with the live list plus the missing ones."""
    account.answer("mode", "exists")
    account.agree()
    for role in (IMAGES_ROLE, DEPLOY_ROLE):
        account.answer(f"live/trust-{role}.json", rendered(TRUST[role], twins=False))
    rc, out = account.run("--confirm")
    assert rc == 0, report(account, out)
    updates = account.calls("^iam update-assume-role-policy$")
    assert sorted(_flag(c, "--role-name") for c in updates) == [DEPLOY_ROLE, IMAGES_ROLE], updates
    assert [c for c in account.calls(CREATES) if c not in updates] == [], report(account, out)
    for role in (IMAGES_ROLE, DEPLOY_ROLE):
        sent = next(c for c in updates if f"--role-name {role} " in c)
        old = subjects(rendered(TRUST[role], twins=False))
        merged = old + [s.replace(f"repo:{REPO}:", TWIN) for s in old]
        assert subjects(_docs(sent).splitlines()[0]) == merged, sent
        assert all(f"trust of {role} gains {s.replace(f'repo:{REPO}:', TWIN)}" in out for s in old)


def test_a_found_role_already_whole_is_not_updated(account: Account) -> None:
    """Both spellings live, in any order: no update call."""
    account.answer("mode", "exists")
    account.agree()
    images = json.loads(rendered("images-trust"))
    images["Statement"][0]["Condition"]["StringLike"][SUB].reverse()
    account.answer(f"live/trust-{IMAGES_ROLE}.json", json.dumps(images))
    rc, out = account.run("--confirm")
    assert rc == 0, report(account, out)
    assert account.calls(CREATES) == [], report(account, out)
    assert f"trust of {IMAGES_ROLE} up to date" in out, out


def test_repository_ids_add_the_id_spelled_subject(account: Account) -> None:
    """`DJB_GITHUB_REPO_IDS` stands in for `gh`'s answer: each subject's twin, nothing wider."""
    account.answer("gh-mode", "fail")
    rc, out = account.run("--confirm", DJB_GITHUB_REPO_IDS="42/4242")
    assert rc == 0, report(account, out)
    assert account.text("gh.argv") == "", "gh was asked although the ids were given"
    made = [c for c in account.calls("^iam create-role$") if f"--role-name {DEPLOY_ROLE} " in c]
    trust = json.loads(_docs(made[0]).splitlines()[0])
    subs = trust["Statement"][0]["Condition"]["StringLike"][
        "token.actions.githubusercontent.com:sub"
    ]
    assert subs == [
        f"repo:{REPO}:ref:refs/heads/main",
        "repo:acme-owner@42/acme-product@4242:ref:refs/heads/main",
    ], subs
    rc, out = account.run("--confirm", DJB_GITHUB_REPO_IDS="42")
    assert rc == 2 and "DJB_GITHUB_REPO_IDS" in out, out


def test_a_piped_stdout_is_refused(account: Account) -> None:
    """The exit status is the verdict; a filter would replace it."""
    with subprocess.Popen(
        ["bash", str(SCRIPT), "--confirm"],
        env=account.env(),
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ) as piped:
        out = piped.communicate()[0].decode(errors="replace")
    assert piped.returncode == 2 and "refuses pipes" in out, out
    assert account.text("aws.argv") == ""


BOX_SIDS = ("ReadAndRewriteThisEnvironmentsOneSecret", "ReadAndWriteThisEnvironmentsTwoBuckets")
# a13's bucket names, before BUCKET-1 qualified them: what R2-DF-20's box role still named.
BARE = {
    f"{NAMESPACE}-{ENV}-{ACCOUNT}-{kind}": f"{NAMESPACE}-{ENV}-{kind}"
    for kind in ("backups", "media")
}


def a13_box(sids: Sequence[str | None] = BOX_SIDS) -> str:
    """The box's `djb-box` as a13 rendered it (bare bucket names), `sids` on its statements."""
    text = rendered("box")
    for qualified, bare in BARE.items():
        text = text.replace(qualified, bare)
    doc = json.loads(text)
    for statement, sid in zip(doc["Statement"], sids, strict=True):
        statement.pop("Sid")
        if sid is not None:
            statement["Sid"] = sid
    return json.dumps(doc)


def _box_puts(made: Account) -> list[str]:
    """The `put-role-policy` calls that named the box role's `djb-box`."""
    return [
        c
        for c in made.calls("^iam put-role-policy$")
        if f"--role-name {BOX_ROLE} " in c and "--policy-name djb-box " in c
    ]


def test_a_template_owned_document_is_rewritten(account: Account) -> None:
    """Template Sids, a13's buckets: the plan says `would rewrite`; --confirm rewrites once."""
    rc, plan = account.run()
    assert rc == 2 and account.text("aws.argv") == "", report(account, plan)
    assert f"{BOX_ROLE} / djb-box" in plan and "would rewrite" in plan, plan
    account.answer("mode", "exists")
    account.agree()
    account.answer(f"live/{BOX_ROLE}--djb-box.json", a13_box())
    rc, out = account.run("--confirm")
    assert rc == 0, report(account, out)
    puts = _box_puts(account)
    assert len(puts) == 1, report(account, out)
    assert _docs(puts[0]) == json.dumps(json.loads(rendered("box"))), puts[0]
    assert [c for c in account.calls(CREATES) if c not in puts] == [], report(account, out)
    rewrote = next((x for x in out.splitlines() if f"rewrote {BOX_ROLE} djb-box" in x), "")
    assert f"template-owned: Sids {','.join(sorted(BOX_SIDS))}" in rewrote, out
    assert all(f"arn:aws:s3:::{bare}" in rewrote for bare in BARE.values()), rewrote
    assert f"--role-name {BOX_ROLE} --policy-name djb-box" not in out, out


@pytest.mark.parametrize(
    "sids",
    [("OpsHandEdit", BOX_SIDS[1]), (*BOX_SIDS, "OpsHandEdit"), (None, None)],
    ids=["a-foreign-sid", "an-added-statement", "an-older-template-without-sids"],
)
def test_a_document_with_any_other_sid_set_is_printed_and_never_rewritten(
    account: Account, sids: tuple[str | None, ...]
) -> None:
    """Hand-edited or Sid-less: compared, the publishing command printed, no `put-role-policy`."""
    account.answer("mode", "exists")
    account.agree()
    doc = json.loads(a13_box(sids[:2]))
    if len(sids) == 3:
        doc["Statement"].append(
            {"Sid": sids[2], "Effect": "Allow", "Action": "s3:ListAllMyBuckets", "Resource": "*"}
        )
    account.answer(f"live/{BOX_ROLE}--djb-box.json", json.dumps(doc))
    rc, out = account.run("--confirm")
    assert rc == 0, report(account, out)
    assert account.calls(CREATES) == [], report(account, out)
    assert f"put-role-policy --role-name {BOX_ROLE} --policy-name djb-box" in out, out
    assert "rewrote" not in out, out


def test_an_identical_document_is_left_alone(account: Account) -> None:
    """The live `djb-box` is what this tree renders: no call, and it says so."""
    account.answer("mode", "exists")
    account.agree()
    rc, out = account.run("--confirm")
    assert rc == 0, report(account, out)
    assert _box_puts(account) == [], report(account, out)
    assert f"inline djb-box on {BOX_ROLE} up to date" in out, out


def test_a_second_confirm_after_a_rewrite_finds_it_up_to_date(account: Account) -> None:
    """Idempotent: the run after a rewrite reads back what it put, and puts nothing."""
    account.answer("mode", "exists")
    account.agree()
    account.answer(f"live/{BOX_ROLE}--djb-box.json", a13_box())
    rc, first = account.run("--confirm")
    assert rc == 0 and len(_box_puts(account)) == 1, report(account, first)
    rc, out = account.run("--confirm")
    assert rc == 0, report(account, out)
    assert len(_box_puts(account)) == 1, report(account, out)
    assert f"inline djb-box on {BOX_ROLE} up to date" in out and "rewrote" not in out, out
