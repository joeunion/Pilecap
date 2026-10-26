"""`manage.py zitadel_measure` — ask the pinned Zitadel what it actually answers.

    uv run python manage.py zitadel_measure

**Every constant in `apps/accounts/zitadel.py` that says MEASURED is a claim
about somebody else's product, and nothing re-asks it.** Twenty of them are
load-bearing: seven field sets that keep a `PUT` from zeroing a deployment's
configuration, the deadline the invitation email prints, the flag that tells an
org's own login policy from the instance's, two refusals the writers' idempotence
is built on, the proto3 rule every reader keys on, the hosted page an invite
link points at, and the twelve facts about the Session API and login v2 that
DESIGN I-A's front door is drawn on — the last of which, M12, is the one the
identity JOIN rests on: that both interactive doors name one person with one
string. Zitadel ships a new minor every few weeks.
The suite cannot check any of it — ADR ident-5(a) settles that the test suite
never dials an external system — so until this existed the whole set was a
docstring nobody could falsify.

This is the falsifier: a hand-run instrument, against the build in
`compose.yaml`, printing one line per fact with the four verdicts the house
grammar allows.

**Four verdicts, and the third is the one that matters.**

    ok                  the build answers what the tree says it answers
    DIFFERS             it answered, and the answer is not what the tree says
    could not           the surface would not answer; NOTHING is asserted here
    unmeasured — <rung> no ingredient exists yet; the rung that lands it is named

`could not` is not a soft `DIFFERS`. A swagger document that 404s tells you
nothing about whether the field sets are right, and an instrument that folded
the two together would let an unreachable instance read as a clean bill — the
exact shape `docs/product/instruments.md` exists to refuse. So it outranks
everything: **exit 0** every item measured and agreeing (or honestly
unmeasured), **exit 1** at least one `DIFFERS`, **exit 2** at least one
`could not`.

**`unmeasured — <rung>` is the closed population's honesty.** Six of the
design's eleven items cannot be measured from this tree today: M1 and M2 need
the login-version declaration A2 writes, M3 and M4 need the auth-request
finalize A8 builds, and M6 and M7 are browser observations A11 makes by hand.
They are PRINTED, every run, naming the rung — because a population that
quietly dropped its unbuilt half would make a twenty-line report look
complete at thirteen. The rung name in the line is what a later builder greps
for.

**It changes no intent, and it builds its own victims.** Every write it makes
is inside an organisation it created seconds earlier under a name beginning
`MEASURE_ORG_PREFIX`, and that organisation — with the one human in it — is
deleted before it returns. The two writes it makes OUTSIDE that org are a `PUT`
of the instance login policy's own live body back to it (the measurement IS
that the build refuses a no-op, and a build that accepted it would have written
the values it already had) and nothing else. **If this process dies between the
create and the delete it leaves that organisation and its human behind**, and
the line it prints before the first measurement says the name to look for.

DOES NOT COVER — declared, and printed beside the verdict on every run, because
a blind spot a reader cannot see is not declared. See `blind_spots()`.
"""

from __future__ import annotations

import re
import secrets
from base64 import urlsafe_b64encode
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import CommandError

# rule-27: the measurement kit is a shell door, and it is the only caller of
# `zitadel.probe` in the tree. It reaches the API to FIND OUT, never to declare:
# every constant it compares against lives in the client module beside the
# writer that depends on it, so the comparison has to happen where both are
# importable. The one organisation it writes into is one it created, and it
# deletes it before returning.
from apps.accounts import zitadel
from apps.accounts import zitadel_measure_kit as kit
from apps.accounts.management.commands.zitadel_seed import LOGIN_BASE_PATH
from apps.core.management import BaseCommand
from apps.core.surfaces import PUBLIC_BASE_URL_SETTING, surface_base_urls

# --- the closed vocabulary ---------------------------------------------------
#
# Four words, and a line begins with exactly one of them. Spelled as constants
# rather than typed at each site so that "every line carries a member of the
# closed set" is a property a test can assert over this tuple rather than a
# regex somebody has to keep in step with the printer.

OK = "ok"
DIFFERS = "DIFFERS"
COULD_NOT = "could not"
UNMEASURED = "unmeasured"

#: Every verdict word a line may begin with. `UNMEASURED` is the prefix of
#: `unmeasured — <rung>`, which is why this is a membership test on the first
#: word and not on the whole line.
VERDICTS = (OK, DIFFERS, COULD_NOT, UNMEASURED)

#: The name every throwaway organisation this command makes begins with. A
#: person who finds one of these on an instance should be able to tell from the
#: name alone that a measurement run died, and that deleting it is safe.
MEASURE_ORG_PREFIX = "pilecap-measure-throwaway"

#: What the authorize endpoint's redirect carries for an application with NO
#: login-version declaration — Zitadel's own hosted page. MEASURED; it is the
#: control half of M1, and a build that stopped answering it is a build where
#: the hosted road moved rather than one where our declaration failed.
V1_AUTHORIZE_MARK = "/ui/login/login?authRequestID="

#: Where the password-reset mail's link lands, and the string that proves the
#: page it lands on is the credential-setting one rather than any other 200
#: the issuer serves at that path — `INVITE_PATH`/C7's shape, for the OTHER
#: mail. MEASURED by hand through a real mail sink on 2026-09-19: the link is
#: `<issuer>/ui/login/password/init?authRequestID=&code=<six>&orgID=&userID=`,
#: served 200 with `<title>Set Password</title>`.
RESET_PATH = "/ui/login/password/init"
RESET_MARK = "Set Password"

#: M12's id, spelled once for the same reason `M3` and `M4` are: the judgment,
#: the population row and the orchestration all name it, and a typo in any one
#: of them is an item that prints beside its own measurement.
M12 = "M12 subject-is-session-user-id"

#: The name every throwaway OIDC client M12 makes begins with. Its own, not
#: mode A's: `check_mode_a` deactivates the client it made inside its own
#: `finally`, so there is nothing left for a second journey to borrow.
SUBJECT_CHECK_PREFIX = "subject-check"

#: The password the throwaway human is given so the Session API's password
#: check has something to verify. It is generated per run rather than fixed:
#: the account it belongs to lives for the length of one command and is deleted
#: with its organisation, and a constant in a repository is a constant somebody
#: eventually reuses somewhere it matters.
PASSWORD_LENGTH = 24


@dataclass(frozen=True)
class Outcome:
    """What one item measured to: a verdict word and the sentence behind it.

    `detail` is not decoration. An `ok` whose detail says what was seen is a
    line the next reader can check against the tree; an `ok` on its own is this
    command agreeing with itself.
    """

    verdict: str
    detail: str


def ok(detail: str) -> Outcome:
    return Outcome(OK, detail)


def differs(detail: str) -> Outcome:
    return Outcome(DIFFERS, detail)


def could_not(detail: str) -> Outcome:
    return Outcome(COULD_NOT, detail)


def unmeasured(rung: str, detail: str) -> Outcome:
    """The rung goes in the VERDICT, not in the detail.

    `unmeasured — A2` is the grammar the criteria name and the string a later
    builder greps for when they are looking for what their own rung has to flip.
    Putting the rung in the trailing prose instead would make that grep find
    every line that merely mentions A2.
    """
    return Outcome(f"{UNMEASURED} — {rung}", detail)


@dataclass(frozen=True)
class Item:
    """One fact, its id, and the sentence saying which claim is under test.

    `subject` is written as the CLAIM rather than as the endpoint, because the
    reader of a `DIFFERS` needs to know what stops being true, not which URL
    was dialled — the URL is in the detail.
    """

    id: str
    subject: str


@dataclass
class World:
    """The throwaway organisation and human, and what is known about them.

    A mutable dataclass rather than a frozen one because it is filled in as the
    run goes: the password is set half way through (the invite-code measurement
    needs a credential-LESS person and the session measurement needs a
    credentialled one, in that order), and the session ids are recorded so the
    teardown can say what it closed.
    """

    org_id: str = ""
    org_name: str = ""
    user_id: str = ""
    login_name: str = ""
    password: str = ""
    invite_code: str = ""
    sessions: list[str] = field(default_factory=list)
    #: Set when the teardown could not remove the organisation, so the verdict
    #: block can name what is still on the instance.
    left_behind: str = ""


# --- the population, closed and in print order -------------------------------
#
# Twenty items: the eight constants this tree already took off the pinned
# build, then the design's M1-M12 in the design's own order. The list is the
# population — a fact with no row here is a fact this command does not measure,
# and `blind_spots()` says which those are. Print order is declaration order so
# two runs are diffable.

ITEMS: tuple[Item, ...] = (
    Item(
        "C1 put-field-sets",
        "every PUT field set in zitadel.PUT_FIELD_SETS equals this build's own "
        "swagger `properties`, and the login policy's two documents agree",
    ),
    Item(
        "C2 invite-code-expiry",
        "SECRET_GENERATOR_TYPE_INVITE_CODE expires in 259200s (three days), "
        "which is the deadline the invitation email prints",
    ),
    Item(
        "C3 is-default",
        "an org with no login policy of its own answers isDefault:true with the "
        "INSTANCE as details.resourceOwner — the audit's one discriminator",
    ),
    Item(
        "C4 org-m0sif",
        "PUT /management/v1/policies/login on an org that has no policy of its "
        "own answers 404 Org-M0sif; it does not quietly create one",
    ),
    Item(
        "C5 instance-5m9vdd",
        "PUT /admin/v1/policies/login with the live body unchanged answers "
        "400 INSTANCE-5M9vdd — which is what makes ensure_login_policy's "
        "compare-before-write the idempotence rather than a saving",
    ),
    Item(
        "C6 proto3-zero-omission",
        "a false boolean is ABSENT from a read, never sent as false — the rule "
        "every *_ABSENT map and every .get(..., False) in the client keys on",
    ),
    Item(
        "C7 invite-path",
        "GET <issuer>/ui/login/user/invite serves the Activate User form and is "
        "not a 404 — where zitadel.invite_url points a person",
    ),
    Item(
        "C8 v2-users-human-empty",
        "POST /v2/users/human with an empty body answers 400 — the v2 user API "
        "is routed and parsing, which is what pins USER = '/v2'",
    ),
    Item(
        "M1 authorize-redirect-per-login-version",
        "the authorize redirect per login version: v1 -> /ui/login/...?"
        "authRequestID=; v2 -> {baseUri}/login?authRequest=V2_...",
    ),
    Item(
        "M2 finalize-needs-login-client",
        "the auth-request finalize needs the IAM_LOGIN_CLIENT manager role; "
        "IAM_OWNER answers 403 AUTH-AWfge",
    ),
    Item(
        "M3 token-carries-client-id",
        "tokens carry client_id and never azp",
    ),
    Item(
        "M4 finalize-refusal-enum",
        "the refusal enum on finalize is ERROR_REASON_*; an RFC lowercase "
        "reason degrades to server_error",
    ),
    Item(
        "M5 session-user-check-is-not-a-password",
        "POST /v2/sessions with a user check and no password check answers 201 "
        "— 2xx is NOT 'the password was right'; only factors.password.verifiedAt is",
    ),
    Item(
        "M6 password-reset-mail-landing",
        "where the password-reset mail's link lands with the application on login v2",
    ),
    Item(
        "M7 zitadel-cookie-after-v2-round-trip",
        "whether a v2 authorize + finalize leaves a Zitadel cookie in the "
        "browser (decides the sign-out sentence)",
    ),
    Item(
        "M8 session-patch-rotates-the-token",
        "a session PATCH that verifies a factor answers a NEW session token; "
        "the ceremony must carry the rotated one",
    ),
    Item(
        "M9 webauthn-no-passkey-is-a-500",
        "a webAuthN challenge for a person with no passkey is a 500, to be read "
        "as 'no passkey here' and never as an outage — and the SAME 500, with "
        "the same id, for a credential bound to another relying party and for "
        "a domain neither party owns, so the id alone never says which",
    ),
    Item(
        "M10 invite-ignores-org-default-redirect",
        "the invite page ignores the org's own defaultRedirectUri — the reason "
        "the invite must land on our page rather than on a redirect Zitadel honours",
    ),
    Item(
        "M11 org-password-complexity",
        "GET /v2/settings/password/complexity answers the org's policy — the "
        "rule sentence the Choose-your-password frame prints",
    ),
    Item(
        "M12 subject-is-session-user-id",
        "the two interactive doors answer the SAME subject for one person: the "
        "`factors.user.id` a session reports to OUR door is byte-identical to "
        "the `sub` an id_token carries to the hosted one",
    ),
)

#: Which rung flips each `unmeasured` item to a check. Read by the printer, so
#: a rung that lands one and forgets to delete its row here leaves a line
#: saying `unmeasured` beside a measurement — which the item's own absence from
#: `measure` would then make impossible. The two halves are kept apart on
#: purpose: this map is the PROMISE, `measure` is the delivery, and a mismatch
#: between them is a failure of `test_every_item_is_measured_or_promised`.
#: The two item ids A8 flipped from a promise to a check, spelled once so the
#: `measure` map, the judgments and the population cannot drift apart on a
#: typo — which for a `PROMISED` key would be an item printing `unmeasured`
#: beside its own measurement.
M3 = "M3 token-carries-client-id"
M4 = "M4 finalize-refusal-enum"
M6 = "M6 password-reset-mail-landing"
M7 = "M7 zitadel-cookie-after-v2-round-trip"

#: **Empty since A11, and that is the point of it being a map.** Every design
#: item has an ingredient now, so every line of the report is a verdict rather
#: than a promise. A future design item arrives here first and leaves when its
#: rung lands; `test_an_unmeasured_item_names_its_rung` is what keeps the two
#: halves honest while it is non-empty.
PROMISED: Mapping[str, str] = {}

#: The swagger definition each declared field set was read out of, and which of
#: this build's two documents holds it. The login policy has TWO entries under
#: one resource key, which is the measurement: `PUT_FIELD_SETS` keys on the path
#: WITHOUT its version prefix precisely because the instance's surface and an
#: org's take the same body, and that is only true while these two definitions
#: carry the same properties.
FIELD_SET_DEFINITIONS: Mapping[str, tuple[tuple[str, str], ...]] = {
    "/policies/login": (
        ("admin", "v1UpdateLoginPolicyRequest"),
        ("management", "v1UpdateCustomLoginPolicyRequest"),
    ),
    "/policies/password/lockout": (("admin", "v1UpdateLockoutPolicyRequest"),),
    "/restrictions": (("admin", "v1SetRestrictionsRequest"),),
    "/policies/label": (("management", "v1UpdateCustomLabelPolicyRequest"),),
    "/idps/generic_oidc/{id}": (("management", "ManagementServiceUpdateGenericOIDCProviderBody"),),
    "/idps/google/{id}": (("management", "ManagementServiceUpdateGoogleProviderBody"),),
    "/projects/{id}/apps/{id}/oidc_config": (
        ("management", "ManagementServiceUpdateOIDCAppConfigBody"),
    ),
    "/projects/{id}": (("management", "ManagementServiceUpdateProjectBody"),),
}

#: The image line in `compose.yaml` this deployment's Zitadel is pinned to, by
#: REGEX rather than by a constant here. A constant would be a second copy of
#: the pin, and the pin moving without this file moving is precisely the event
#: the version block exists to make visible.
COMPOSE_PIN = re.compile(r"^\s*image:\s*(ghcr\.io/zitadel/zitadel:\S+)\s*$", re.MULTILINE)


def compose_pin(root: Path | None = None) -> str:
    """The image tag `compose.yaml` pins, or a sentence saying it could not be read.

    Deliberately NOT compared against anything (I5.3). The running instance does
    not publish its own version on any unauthenticated surface this instrument
    can reach, so an equality here would be an assertion between the pin and
    itself. What the block is for is that a reader of a `DIFFERS` six weeks from
    now can see which build the disagreement is about.
    """
    base = root or Path(settings.BASE_DIR)
    path = base / "compose.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return f"could not read {path}: {error}"
    found = COMPOSE_PIN.search(text)
    return found.group(1) if found else f"no zitadel image line in {path}"


def blind_spots() -> list[str]:
    """What a clean twenty-line run does NOT cover, printed beside the verdict.

    The same shape, and the same reason, as `zitadel_audit.blind_spot_lines`: a
    blind spot declared only in a module docstring is a blind spot the person
    reading the green report does not have.
    """
    return [
        "does not cover",
        "  The measurement is POINT-IN-TIME against ONE build — the tag printed",
        "  in the version block above. It says nothing about the build a",
        "  deployment other than this laptop is running, and running it again is",
        "  the only diff there is.",
        "  It measures what the API ANSWERS, never what the writers above it",
        "  send: that a declared field set equals the swagger is not that the",
        "  writer sends the whole set — `apps/accounts/tests/test_zitadel_full_body.py`",
        "  is the census that asks that, and it runs in the suite.",
        "  M9's THIRD half — that our own host's relying-party id is accepted",
        "  for a begin AND a finish — needs a registered credential, which needs",
        "  an authenticator, which is not something a management walk has. A9",
        "  drove it with a virtual authenticator against a throwaway person and",
        "  recorded the answers (begin 201, finish 200, from a login name and",
        "  with no password); what is measured HERE is the two halves that need",
        "  no credential. And no walk of any kind can see the half that matters",
        "  most in a browser: a relying-party id that is an IP address is",
        "  accepted by this server and refused by every browser, which is what",
        "  `signin.passkey_road_open` exists for.",
        "  M5 and M8 are measured on a person this run created, in an",
        "  organisation this run created. A tenant's own people, a federated",
        "  identity and an org carrying a policy somebody configured are all",
        "  outside the walk.",
        "  M12 measures OUR instance, on a person this run made, through the",
        "  ONE session both halves are read off. It says nothing about a subject",
        "  a FEDERATED identity provider asserts through an `SsoConnection` —",
        "  that subject is `SsoIdentity.subject`, a different column with a",
        "  different writer — and nothing about a build a deployment other than",
        "  this laptop is running.",
        "  M1 and M12 each leave a DEACTIVATED throwaway OIDC client under this",
        "  deployment's own project, one per run, named",
        "  `login-version-check-<hex>` and `subject-check-<hex>`. Deactivated is",
        "  not a door, and the",
        "  object is the evidence a measurement was taken — but a deployment",
        "  measured daily accumulates them, and nothing sweeps them.",
        "  Nothing here reaches the console, the instance's actions, its machine",
        "  keys or any organisation but the one it made. House rule 27 fences",
        "  this codebase; it cannot fence the console.",
        "  The `unmeasured` items are NOT judged and NOT covered: a green run",
        "  carrying them is a run over the items it actually measured, and the",
        "  count in the verdict line is what says how many that was.",
    ]


# --- the throwaway world -----------------------------------------------------


@contextmanager
def throwaway(stdout: Any, world: World) -> Iterator[World]:
    """Build the organisation and human this run measures in, then remove them.

    The name is stamped and salted: stamped so a leaked one says WHEN the run
    that leaked it happened, salted so two runs a second apart cannot collide on
    an instance. The name is printed BEFORE the create, not after, because the
    window this sentence is for is the one where the process dies during it.
    """
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    world.org_name = f"{MEASURE_ORG_PREFIX}-{stamp}-{secrets.token_hex(3)}"
    world.login_name = f"{world.org_name}@pilecap.invalid"
    world.password = secrets.token_urlsafe(PASSWORD_LENGTH) + "aA1!"
    stdout.write(
        f"victims     creating organisation {world.org_name!r} and one human in it. "
        "If this run dies before the teardown line below, that organisation and "
        "its human are what is left on the instance; deleting it is safe."
    )
    try:
        yield world
    finally:
        if world.org_id:
            removed = zitadel.remove_organization(org_id=world.org_id)
            if removed:
                stdout.write(
                    f"victims     removed organisation {world.org_name!r} "
                    f"({world.org_id}) and the human in it."
                )
            else:
                world.left_behind = f"{world.org_name} ({world.org_id})"
                stdout.write(
                    f"victims     COULD NOT REMOVE organisation {world.org_name!r} "
                    f"({world.org_id}). It is still on the instance, with its one "
                    "human. Delete it by hand."
                )


def build_world(world: World) -> None:
    """Create the organisation and the credential-LESS human, in that order.

    Credential-less is the state M10 needs — `CreateInviteCode` refuses a person
    who has already set a password (`COMMAND-EF34g`) — so the password is set
    later, after the invite code has been minted. Raising here is correct: a
    world that could not be built makes every item that needs it `could not`,
    which the caller turns into exit 2.
    """
    world.org_id = zitadel.create_organization(name=world.org_name).id
    if not world.org_id:
        raise zitadel.ZitadelError("Zitadel created an organisation and returned no id")
    made = zitadel.probe(
        "POST",
        "/users/human",
        {
            "username": world.login_name,
            "organization": {"orgId": world.org_id},
            "profile": {"givenName": "Measurement", "familyName": "Throwaway"},
            "email": {"email": world.login_name, "isVerified": True},
        },
        prefix=zitadel.USER,
    )
    if not made.ok:
        raise zitadel.ZitadelError(
            f"Zitadel refused the throwaway human: {made.status} {made.text[:200]}"
        )
    world.user_id = str(made.body.get("userId", ""))
    if not world.user_id:
        raise zitadel.ZitadelError("Zitadel created a human and returned no userId")


# --- the measurements --------------------------------------------------------
#
# One function per item, each returning an `Outcome`. They are called in an
# OPERATIONAL order below — C3 and C4 must run before M10 writes the org a
# policy of its own, and M10 must mint its invite code before M8 gives the
# person a password — and PRINTED in the declared order of `ITEMS`. Keeping the
# two orders apart is what lets the report be diffable while the world is built
# up in the only sequence Zitadel allows.


def measure_field_sets() -> Outcome:
    """C1 — every declared field set against this build's own swagger."""
    documents = {name: kit.swagger_document(name=name) for name in ("admin", "management")}
    wrong: list[str] = []
    seen: list[str] = []
    for resource, definitions in FIELD_SET_DEFINITIONS.items():
        declared = zitadel.PUT_FIELD_SETS[resource]
        live: dict[str, frozenset[str]] = {}
        for document, definition in definitions:
            found = (documents[document].get("definitions") or {}).get(definition)
            if not isinstance(found, dict) or "properties" not in found:
                wrong.append(f"{resource}: {document} swagger has no {definition}")
                continue
            live[definition] = frozenset(found["properties"])
        for definition, properties in live.items():
            missing = sorted(properties - declared)
            extra = sorted(declared - properties)
            if missing or extra:
                wrong.append(
                    f"{resource} vs {definition}: declared-but-gone {extra}, "
                    f"served-but-undeclared {missing}"
                )
        if len(live) == 2:
            first, second = live.values()
            if first != second:
                names = " vs ".join(live)
                wrong.append(
                    f"{resource}: the two documents disagree ({names}): "
                    f"{sorted(set(first) ^ set(second))}"
                )
        seen.append(f"{resource}={len(declared)}")
    if wrong:
        return differs("; ".join(wrong))
    return ok(
        f"{len(FIELD_SET_DEFINITIONS)} resources, field counts {', '.join(seen)}; "
        "the login policy's two documents carry the same properties"
    )


def measure_invite_expiry() -> Outcome:
    """C2 — the invitation email's deadline, from the instance's own generator."""
    answer = zitadel.probe("POST", "/secretgenerators/_search", {}, prefix=zitadel.ADMIN)
    if not answer.ok:
        return could_not(f"POST /admin/v1/secretgenerators/_search answered {answer.status}")
    for row in answer.body.get("result") or []:
        if str(row.get("generatorType", "")) != "SECRET_GENERATOR_TYPE_INVITE_CODE":
            continue
        expiry = str(row.get("expiry", ""))
        detail = f"expiry={expiry}, length={row.get('length')}"
        return ok(detail) if expiry == "259200s" else differs(f"{detail}, expected 259200s")
    return differs("the instance serves no SECRET_GENERATOR_TYPE_INVITE_CODE generator")


def measure_is_default(world: World) -> Outcome:
    """C3 — a fresh org inherits, and says so with one flag."""
    answer = zitadel.probe("GET", "/policies/login", prefix=zitadel.MANAGEMENT, org_id=world.org_id)
    if not answer.ok:
        return could_not(f"GET /management/v1/policies/login answered {answer.status}")
    policy = dict(answer.body.get("policy") or {})
    owner = str((policy.get("details") or {}).get("resourceOwner", ""))
    flag = policy.get("isDefault")
    if flag is not True:
        return differs(
            f"a throwaway org's login policy carries isDefault={flag!r}, so the audit's "
            "own/inherited discriminator no longer holds"
        )
    if owner == world.org_id:
        return differs(
            f"isDefault:true but details.resourceOwner is the ORG ({owner}); the flag and "
            "the owner no longer agree about who the policy belongs to"
        )
    return ok(f"isDefault=true, details.resourceOwner={owner} (the instance, not {world.org_id})")


def measure_org_m0sif(world: World) -> Outcome:
    """C4 — the org update endpoint refuses an org that inherits."""
    answer = zitadel.probe(
        "PUT",
        "/policies/login",
        {key: value for key, value in zitadel.LOGIN_POLICY_ABSENT.items()},
        prefix=zitadel.MANAGEMENT,
        org_id=world.org_id,
    )
    if answer.status == 404 and answer.error_id == "Org-M0sif":
        return ok(f"404 {answer.error_id} — {answer.body.get('message', '')}")
    return differs(
        f"answered {answer.status} {answer.error_id or answer.text[:120]!r}; a build that "
        "CREATED the org a policy here would fork this deployment's configuration into "
        "two owners without anybody asking"
    )


def measure_instance_5m9vdd() -> Outcome:
    """C5 — the instance update endpoint refuses a body that changes nothing.

    The one write this command makes outside its own organisation, and it is a
    no-op by construction: the body is the live policy read back, field for
    field, which is exactly what `ensure_login_policy` builds when the desired
    state already holds. A build that ACCEPTED it would have written the values
    it already had — which is why the acceptance is a `DIFFERS` and not damage.
    """
    live = zitadel.probe("GET", "/policies/login", prefix=zitadel.ADMIN)
    if not live.ok:
        return could_not(f"GET /admin/v1/policies/login answered {live.status}")
    policy = dict(live.body.get("policy") or {})
    body = {key: policy.get(key, absent) for key, absent in zitadel.LOGIN_POLICY_ABSENT.items()}
    answer = zitadel.probe("PUT", "/policies/login", body, prefix=zitadel.ADMIN)
    if answer.status == 400 and answer.error_id == "INSTANCE-5M9vdd":
        return ok(f"400 {answer.error_id} — {answer.body.get('message', '')}")
    if answer.ok:
        return differs(
            f"answered {answer.status}: this build ACCEPTS a no-op PUT, so "
            "ensure_login_policy's compare-before-write is now the only thing "
            "keeping a second identical write from being a second event"
        )
    return differs(f"answered {answer.status} {answer.error_id or answer.text[:120]!r}")


def measure_proto3_zero_omission() -> Outcome:
    """C6 — a false boolean is absent, not `false`."""
    live = zitadel.probe("GET", "/policies/login", prefix=zitadel.ADMIN)
    if not live.ok:
        return could_not(f"GET /admin/v1/policies/login answered {live.status}")
    policy = dict(live.body.get("policy") or {})
    booleans = [
        key for key, absent in zitadel.LOGIN_POLICY_ABSENT.items() if isinstance(absent, bool)
    ]
    sent_false = sorted(key for key in booleans if policy.get(key) is False)
    absent = sorted(key for key in booleans if key not in policy)
    if sent_false:
        return differs(
            f"the instance login policy sends {sent_false} as false rather than omitting "
            "them; every *_ABSENT map and every .get(..., False) in the client is keyed "
            "on the omission"
        )
    if not absent:
        return could_not(
            "every declared boolean on the instance login policy is true, so this read "
            "cannot show an omission — nothing was asserted"
        )
    return ok(
        f"{len(absent)} of {len(booleans)} declared booleans absent rather than false: {absent}"
    )


def measure_invite_path() -> Outcome:
    """C7 — the hosted page `invite_url` points a person at is still served."""
    answer = zitadel.probe("GET", f"{zitadel.INVITE_PATH}?userID=0&code=MEASURE", prefix="")
    if answer.status == 404:
        return differs(
            f"GET {zitadel.INVITE_PATH} answered 404 — zitadel.invite_url now points every "
            "invited person at a page that does not exist"
        )
    if not answer.ok:
        return could_not(f"GET {zitadel.INVITE_PATH} answered {answer.status}")
    has_form = "passwordconfirm" in answer.text.lower()
    detail = f"{answer.status}, {len(answer.text)} bytes, password-confirm field {has_form}"
    return ok(detail) if has_form else differs(f"{detail} — served, but not the Activate User form")


def measure_v2_users_human_empty() -> Outcome:
    """C8 — the v2 user surface is routed, and parsing."""
    answer = zitadel.probe("POST", "/users/human", {}, prefix=zitadel.USER)
    if answer.status == 400:
        return ok(f"400 — {answer.body.get('message', answer.text[:120])}")
    if answer.status == 404:
        return differs(
            "404 — the v2 user API is not routed at this prefix, so zitadel.USER is wrong "
            "and every invitation this deployment mints goes through a path that 404s"
        )
    return differs(f"answered {answer.status} {answer.text[:160]!r}, expected 400")


def measure_authorize_redirect() -> Outcome:
    """M1 — where the authorize endpoint sends a person, per login version.

    **The one measurement that writes into a REAL project**, and the cost is
    stated rather than hidden: `kit.check_login_version_redirects` makes a
    throwaway native application under this deployment's own project, measures
    the redirect twice (undeclared, then with `loginVersion.loginV2.baseUri`),
    and DEACTIVATES it in a `finally`. A deactivated client is not a door, and
    the object is left rather than deleted because Zitadel's audit log reads
    better with a deactivation in it than with a gap — so a run a week leaves a
    week of them, by name, and the caller prints that.

    It cannot be measured on the real Web application: that is the object every
    person signs in through, and two live declaration changes on it is the one
    breakage that locks a deployment out of its own front door.
    """
    project_name = str(getattr(settings, "ZITADEL_PROJECT_NAME", "") or "")
    project = zitadel.find_project(name=project_name) if project_name else None
    if not project:
        return could_not(
            f"this deployment has no project named {project_name!r} — "
            "`manage.py zitadel_seed` has not run here, so there is nothing to "
            "make a throwaway client under"
        )
    # The URI this deployment WOULD declare under `SIGN_IN_DOOR=ours`, built
    # from the one path `zitadel_seed.LOGIN_BASE_PATH` declares rather than
    # spelled again here. It is handed to a THROWAWAY client, so it is a
    # measurement input and not the deployment's intent —
    # `zitadel_seed.declared_login_base_uri` is the intent and answers `None`
    # until A5, which is why this does not call it.
    public = surface_base_urls()[0]
    if not public:
        return could_not(
            f"{PUBLIC_BASE_URL_SETTING} is empty, so there is no base URI to declare and the "
            "v2 half of this measurement has nothing to compare against"
        )
    base_uri = f"{public}{LOGIN_BASE_PATH}"
    seen = kit.check_login_version_redirects(
        project_id=str(project.get("id", "")), base_uri=base_uri
    )
    undeclared, declared = seen["undeclared"], seen["declared"]
    wrong: list[str] = []
    if V1_AUTHORIZE_MARK not in undeclared:
        wrong.append(
            f"with NO declaration the authorize endpoint answered {undeclared!r}, "
            f"which does not carry {V1_AUTHORIZE_MARK!r} — the hosted page is no "
            "longer where an undeclared application sends a person"
        )
    wanted = f"{base_uri}/login?authRequest=V2_"
    if not declared.startswith(wanted):
        wrong.append(
            f"WITH loginVersion.loginV2.baseUri={base_uri!r} it answered {declared!r}, "
            f"which does not start with {wanted!r} — the per-application declaration "
            "no longer moves the front door, and SIGN_IN_DOOR=ours would send every "
            "person to the hosted page"
        )
    if wrong:
        return differs("; ".join(wrong))
    return ok(
        f"undeclared -> {undeclared}; declared -> {declared[: len(wanted) + 12]}… "
        "(one throwaway client made under this deployment's project and deactivated)"
    )


def measure_login_client_role() -> Outcome:
    """M2 — whether this deployment's credential may finalize a v2 login.

    A READ, not an attempted finalize: a finalize needs a real auth request and
    a real session, so measuring it directly would mean signing somebody in,
    and the role is the whole of what the `403 AUTH-AWfge` is about.

    A missing role is `DIFFERS` and not `could not`: the surface answered, and
    what it said is that this deployment cannot finish a sign-in on its own
    page. That is a fact about the deployment, which is what this instrument
    is for — the remedy is `manage.py zitadel_reconcile`, and the line says so.
    """
    seen = kit.check_login_client_role()
    roles = ", ".join(str(one) for one in seen["roles"]) or "none"
    if not seen["user_id"]:
        return could_not(
            "GET /auth/v1/users/me named no user, so there is no credential to ask about"
        )
    if not seen["may_finalize"]:
        return differs(
            f"the machine credential {seen['login_name']!r} holds [{roles}] and NOT "
            f"{zitadel.LOGIN_CLIENT_ROLE} — a login-v2 finalize answers 403 AUTH-AWfge, "
            "so SIGN_IN_DOOR=ours cannot finish a sign-in here. "
            "`manage.py zitadel_reconcile --kind posture` grants it"
        )
    return ok(
        f"the machine credential {seen['login_name']!r} ({seen['user_id']}) holds "
        f"[{roles}], {zitadel.LOGIN_CLIENT_ROLE} among them"
    )


def measure_session_user_check(world: World) -> Outcome:
    """M5 — a 2xx from the Session API is not a verified password."""
    answer = zitadel.probe(
        "POST",
        "/sessions",
        {"checks": {"user": {"userId": world.user_id}}},
        prefix=zitadel.USER,
        org_id=world.org_id,
    )
    if answer.status != 201:
        return differs(
            f"POST /v2/sessions with a user check answered {answer.status} "
            f"{answer.error_id or answer.text[:120]!r}, expected 201"
        )
    session_id = str(answer.body.get("sessionId", ""))
    world.sessions.append(session_id)
    read = zitadel.probe("GET", f"/sessions/{session_id}", prefix=zitadel.USER)
    if not read.ok:
        return could_not(
            f"the session was created and GET /v2/sessions/{{id}} answered {read.status}"
        )
    factors = dict((read.body.get("session") or {}).get("factors") or {})
    if "password" in factors:
        return differs(
            "a session created with a USER check alone already carries "
            f"factors.password={factors['password']!r} — the fail-closed rule that reads "
            "factors.password.verifiedAt would now pass a person who typed nothing"
        )
    return ok(
        f"201, factors={sorted(factors)} — user verified, password absent, so 2xx is not "
        "'the password was right'"
    )


def measure_session_patch_rotates(world: World) -> Outcome:
    """M8 — the token the ceremony must carry forward.

    Two PATCHes, because one of them turned out to be the news: the PATCH that
    VERIFIES a factor answers a new token, and a PATCH that verifies nothing
    answers **no token at all** rather than the same one. Both are reported in
    the line, because a ceremony that assumed a token in every answer would
    carry `None` forward on the second shape.
    """
    if not world.user_id:
        return could_not("no throwaway human to open a session for")
    opened = zitadel.probe(
        "POST",
        "/sessions",
        {"checks": {"user": {"userId": world.user_id}}},
        prefix=zitadel.USER,
        org_id=world.org_id,
    )
    if opened.status != 201:
        return could_not(f"POST /v2/sessions answered {opened.status} — no session to PATCH")
    session_id = str(opened.body.get("sessionId", ""))
    token = str(opened.body.get("sessionToken", ""))
    world.sessions.append(session_id)
    checked = zitadel.probe(
        "PATCH",
        f"/sessions/{session_id}",
        {"sessionToken": token, "checks": {"password": {"password": world.password}}},
        prefix=zitadel.USER,
        org_id=world.org_id,
    )
    if not checked.ok:
        return could_not(
            f"PATCH /v2/sessions/{{id}} with a password check answered {checked.status} "
            f"{checked.error_id or checked.text[:120]!r}"
        )
    rotated = str(checked.body.get("sessionToken", ""))
    if not rotated:
        return differs(
            "a PATCH that verified the password answered NO sessionToken, so the ceremony "
            "has nothing to carry forward"
        )
    if rotated == token:
        return differs("the PATCH answered the SAME session token; nothing rotated")
    quiet = zitadel.probe(
        "PATCH",
        f"/sessions/{session_id}",
        {"sessionToken": rotated, "metadata": {}},
        prefix=zitadel.USER,
        org_id=world.org_id,
    )
    tail = (
        "and a PATCH that verifies nothing answers no sessionToken at all"
        if quiet.ok and not quiet.body.get("sessionToken")
        else f"a no-op PATCH answered {quiet.status} with sessionToken "
        f"{bool(quiet.body.get('sessionToken'))}"
    )
    zitadel.probe(
        "DELETE",
        f"/sessions/{session_id}",
        {"sessionToken": str(quiet.body.get("sessionToken") or rotated)},
        prefix=zitadel.USER,
        org_id=world.org_id,
    )
    return ok(f"a password check rotates the token ({len(rotated)} bytes), {tail}")


def measure_webauthn_no_passkey(world: World) -> Outcome:
    """M9 — the 500 that means "no passkey here"."""
    answer = zitadel.probe(
        "POST",
        "/sessions",
        {
            "checks": {"user": {"userId": world.user_id}},
            "challenges": {
                "webAuthN": {
                    "domain": "localhost",
                    "userVerificationRequirement": "USER_VERIFICATION_REQUIREMENT_REQUIRED",
                }
            },
        },
        prefix=zitadel.USER,
        org_id=world.org_id,
    )
    if answer.status == 500:
        # **The same probe, twice more, for the two facts A9 needed and this
        # item did not carry.** Neither needs a credential, both change how
        # the one error id may be read, and a line that reported only the
        # no-passkey half would leave a reader believing the id means it.
        elsewhere = zitadel.probe(
            "POST",
            "/sessions",
            {
                "checks": {"user": {"userId": world.user_id}},
                "challenges": {
                    "webAuthN": {
                        "domain": "a-host-neither-party-owns.invalid",
                        "userVerificationRequirement": "USER_VERIFICATION_REQUIREMENT_REQUIRED",
                    }
                },
            },
            prefix=zitadel.USER,
            org_id=world.org_id,
        )
        nameless = zitadel.probe(
            "POST",
            "/sessions",
            {
                "challenges": {
                    "webAuthN": {
                        "domain": "localhost",
                        "userVerificationRequirement": "USER_VERIFICATION_REQUIREMENT_REQUIRED",
                    }
                }
            },
            prefix=zitadel.USER,
            org_id=world.org_id,
        )
        for spent in (elsewhere, nameless):
            if spent.ok:
                world.sessions.append(str(spent.body.get("sessionId", "")))
        same = elsewhere.status == answer.status and elsewhere.error_id == answer.error_id
        return ok(
            f"500 {answer.error_id} — {answer.body.get('message', '')}; a seam that treated "
            "this as an outage would retry a person who simply has no passkey. "
            f"A domain neither party owns answers {elsewhere.status} "
            f"{elsewhere.error_id or '-'}"
            f"{' — THE SAME, so the id never says WHY' if same else ''}. "
            f"The usernameless (discoverable) road answers {nameless.status} "
            f"{nameless.error_id or '-'}"
            + (
                " — there is no discoverable passkey road on this build"
                if nameless.error_id == zitadel.WEBAUTHN_USER_REQUIRED
                else ""
            )
        )
    if answer.status == 201:
        world.sessions.append(str(answer.body.get("sessionId", "")))
        return differs(
            "201 — this build now issues a WebAuthn challenge for a person with no "
            "registered credential, so 'a 500 means no passkey' is no longer how to read it"
        )
    return differs(
        f"answered {answer.status} {answer.error_id or answer.text[:120]!r}, expected 500"
    )


def measure_invite_ignores_redirect(world: World) -> Outcome:
    """M10 — the org's default redirect does not move the invite.

    Writes the throwaway org a login policy OF ITS OWN carrying a
    `defaultRedirectUri` nothing else on this instance points at, then fetches
    the invite link that org's one human would be sent. **This runs after C3 and
    C4**, which need the org still inheriting, and it mints the code before M8
    gives the person a password — `CreateInviteCode` refuses an initialised one.
    """
    marker = "https://measure-default-redirect.invalid/landing"
    created = zitadel.probe(
        "POST",
        "/policies/login",
        {"allowUsernamePassword": True, "defaultRedirectUri": marker},
        prefix=zitadel.MANAGEMENT,
        org_id=world.org_id,
    )
    if not created.ok:
        return could_not(
            f"POST /management/v1/policies/login answered {created.status} — the org has no "
            "default redirect to ignore, so nothing was asserted"
        )
    minted = zitadel.probe(
        "POST", f"/users/{world.user_id}/invite_code", {"returnCode": {}}, prefix=zitadel.USER
    )
    if not minted.ok:
        return could_not(
            f"POST /v2/users/{{id}}/invite_code answered {minted.status} "
            f"{minted.error_id or minted.text[:120]!r}"
        )
    world.invite_code = str(minted.body.get("inviteCode", ""))
    landed = zitadel.probe(
        "GET",
        f"{zitadel.INVITE_PATH}?userID={world.user_id}&code={world.invite_code}",
        prefix="",
    )
    if landed.status in (301, 302, 303, 307, 308):
        return differs(
            f"the invite link answered {landed.status} — a redirect Zitadel honours, so an "
            "invited person would not land on the page the design puts them on"
        )
    if not landed.ok:
        return could_not(f"the invite link answered {landed.status}")
    if marker in landed.text:
        return differs(
            f"the invite page carries the org's defaultRedirectUri ({marker}), so the "
            "landing is the org's and not ours"
        )
    return ok(
        f"the org's own policy declares defaultRedirectUri={marker} and the invite link "
        f"still answers {landed.status} with the Activate User form, no Location, no marker"
    )


def measure_password_complexity(world: World) -> Outcome:
    """M11 — the rule sentence the Choose-your-password frame has to print."""
    answer = zitadel.probe(
        "GET",
        f"/settings/password/complexity?ctx.orgId={world.org_id}",
        prefix=zitadel.USER,
    )
    if not answer.ok:
        return could_not(
            f"GET /v2/settings/password/complexity answered {answer.status} "
            f"{answer.error_id or answer.text[:120]!r}"
        )
    found = dict(answer.body.get("settings") or {})
    if not found:
        return differs("answered 200 with no `settings` block; there is no rule to print")
    shape = ", ".join(f"{key}={found[key]}" for key in sorted(found))
    return ok(shape)


def measure_mode_a(world: World) -> dict[str, Outcome]:
    """**M3, M4 and M7 together**, because they are one journey and one victim.

    The whole v2 round trip on a throwaway native client under this
    deployment's own project: authorize with `loginVersion` declared, open a
    session for the throwaway human, finalize, spend the code, read the
    token's claim names — then refuse two fresh auth requests, once in each
    spelling, and read what reaches the client.

    Returns BOTH items, so a world that could not be built says `could not`
    for both with the same reason rather than leaving one of them looking
    measured. Called after M8, because the human needs the password M8's
    prelude gives them.
    """
    project_name = str(getattr(settings, "ZITADEL_PROJECT_NAME", "") or "")
    project = zitadel.find_project(name=project_name) if project_name else None
    public = surface_base_urls()[0]
    if not project or not public:
        blocked = could_not(
            f"no project named {project_name!r} on this instance, or {PUBLIC_BASE_URL_SETTING} "
            "is empty — "
            "there is nothing to make a throwaway OIDC client under, and no base URI "
            "for it to declare"
        )
        return {M3: blocked, M4: blocked, M7: blocked}

    seen = kit.check_mode_a(
        project_id=str(project.get("id", "")),
        base_uri=f"{public}{LOGIN_BASE_PATH}",
        login_name=world.login_name,
        password=world.password,
        org_id=world.org_id,
    )
    return {
        M3: _judge_token_claims(seen),
        M4: _judge_refusal_enum(seen),
        M7: _judge_sso_after_finalize(seen),
    }


def _judge_token_claims(seen: Mapping[str, Any]) -> Outcome:
    """M3 — which claim names the build puts in a token, and what is in them.

    The consumer's V-181 said "tokens carry `client_id`, never `azp`". Both
    halves are checked, and they are checked PER TOKEN KIND, because this
    build does not answer the same way for the two: measured on 2026-09-19,
    the ACCESS token carries `client_id` and no `azp`, and the ID token
    carries both. `apps/accounts/oauth.py` validates the access token, so the
    access token's half is the one that governs; the id token's `azp` is
    reported rather than judged.
    """
    if seen.get("trouble"):
        return could_not(str(seen["trouble"]))
    access = seen.get("access_token_claims")
    if not access:
        return could_not("the token exchange answered no access token to read claims off")
    client_id = seen.get("access_token_client_id")
    azp = seen.get("access_token_azp")
    if not client_id:
        return differs(
            f"the access token carries no `client_id` claim (it carries {access}) — "
            "the resource server reads that claim to know which client is calling"
        )
    if azp:
        return differs(
            f"the access token carries `azp`={azp!r} as well as `client_id`={client_id!r}; "
            "a reader that preferred `azp` would now get an answer, which is the "
            "ambiguity V-181 was about"
        )
    return ok(
        f"the access token carries client_id={client_id!r} and no azp "
        f"({len(access)} claims: {', '.join(access)}); the ID token beside it carries "
        f"BOTH client_id and azp={seen.get('id_token_azp')!r} — reported, not judged: "
        "the resource server reads the ACCESS token"
    )


def _judge_refusal_enum(seen: Mapping[str, Any]) -> Outcome:
    """M4 — the enum spelling survives, and the RFC one degrades.

    Both halves, because either alone is satisfied by a build that ignores
    the field entirely: a run that only checked the enum could not tell
    "Zitadel honoured our reason" from "Zitadel says access_denied for
    everything", and a run that only checked the degradation could not tell
    it from "Zitadel says server_error for everything".
    """
    if seen.get("trouble") and "enum_error" not in seen:
        return could_not(str(seen["trouble"]))
    enum_error = str(seen.get("enum_error", ""))
    rfc_error = str(seen.get("rfc_error", ""))
    if not enum_error and not rfc_error:
        return could_not("neither refusal reached a callback URL, so there is nothing to read")
    wrong: list[str] = []
    if enum_error != "access_denied":
        wrong.append(
            f"{zitadel.REFUSE_ACCESS_DENIED} reached the client as {enum_error!r}, "
            "expected 'access_denied' — the reason this tree sends no longer arrives"
        )
    if rfc_error != "server_error":
        wrong.append(
            f"the RFC lowercase spelling 'access_denied' reached the client as "
            f"{rfc_error!r}, expected 'server_error' — the degradation this item "
            "warns about has changed, and the enum spelling may no longer be required"
        )
    if wrong:
        return differs("; ".join(wrong))
    return ok(
        f"{zitadel.REFUSE_ACCESS_DENIED} -> error={enum_error}; the RFC lowercase "
        f"spelling -> error={rfc_error} (a client told the authorization server broke), "
        "which is why the enum spelling is the one signin.refuse sends"
    )


def _unverified_subject(token: str) -> str:
    """A JWT's `sub`, WITHOUT verifying the signature. For a measurement only."""
    return str(kit.unverified_claims(token).get("sub", ""))


def _one_person_through_both_doors(world: World) -> dict[str, Any]:
    """**M12's journey: ONE session, read twice, once per door.**

    A session is opened for the throwaway human with a user check and a
    password check — which is what `signin.py` does at OUR door — and two
    things are then read off that same session:

    * what **our** door reads: `factors.user.id`, from `GET /v2/sessions/{id}`;
    * what the **hosted** door reads: the `sub` of an id_token, by finalizing
      an auth request against that session and spending the code it answers.

    One session rather than two, because the claim is that one person's one
    sign-in is one identity fact. Two sessions would measure two people who
    happen to share an id, which is trivially true and not the question.

    **It builds its own victim and deactivates it**, `check_mode_a`'s rule and
    for its reason: the deployment's real browser client is what every person
    signs in through, and a declaration change on it is the one breakage that
    locks a deployment out of its own front door.

    Returns facts, never a verdict — `measure_subject_is_session_user_id`
    judges — with `trouble` naming the leg that would not answer.
    """
    found: dict[str, Any] = {"trouble": ""}
    if not world.user_id:
        found["trouble"] = "no throwaway human to open a session for"
        return found
    project_name = str(getattr(settings, "ZITADEL_PROJECT_NAME", "") or "")
    project = zitadel.find_project(name=project_name) if project_name else None
    public = surface_base_urls()[0]
    if not project or not public:
        found["trouble"] = (
            f"no project named {project_name!r} on this instance, or {PUBLIC_BASE_URL_SETTING} "
            "is empty — "
            "there is nothing to make a throwaway OIDC client under, so no id_token can "
            "be minted and nothing is asserted here"
        )
        return found

    project_id = str(project.get("id", ""))
    base_uri = f"{public}{LOGIN_BASE_PATH}"
    redirect_uri = f"{base_uri.rstrip('/')}/{SUBJECT_CHECK_PREFIX}/callback"
    made = zitadel.ensure_native_application(
        project_id=project_id,
        name=f"{SUBJECT_CHECK_PREFIX}-{secrets.token_hex(6)}",
        redirect_uris=[redirect_uri],
        dev_mode=True,
    )
    client_id = str(made.detail.get("clientId", ""))
    try:
        zitadel.ensure_application_login_version(
            project_id=project_id, app_id=made.id, base_uri=base_uri
        )
        opened = zitadel.open_session(
            checks={
                "user": {"userId": world.user_id},
                "password": {"password": world.password},
            },
            org_id=world.org_id,
        )
        if opened.status != 201:
            found["trouble"] = (
                f"POST /v2/sessions for the throwaway human answered {opened.status} "
                f"{opened.error_id or opened.text[:120]!r} — there is no session to read "
                "either door's answer off"
            )
            return found
        session_id = str(opened.body.get("sessionId", ""))
        session_token = str(opened.body.get("sessionToken", ""))
        world.sessions.append(session_id)

        read = zitadel.read_session(session_id=session_id)
        if not read.ok:
            found["trouble"] = f"GET /v2/sessions/{{id}} answered {read.status}"
            return found
        factors = dict((read.body.get("session") or {}).get("factors") or {})
        found["factors"] = sorted(factors)
        found["session_user_id"] = str((factors.get("user") or {}).get("id", ""))

        verifier = secrets.token_hex(48)
        challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
        # **Both legs go through the client module's own factory**, which is
        # what `check_mode_a` uses and what the suite's fake intercepts.
        # `zitadel.probe` cannot model either: the authorize's whole answer is
        # a `Location` HEADER, which `Probe` does not carry, and the token
        # endpoint takes a FORM body, which `probe` does not send. The
        # credential the factory attaches is ignored by both — measured, and
        # recorded on `kit.authorize_redirect`: the 302 was taken with it on.
        with zitadel._client() as browser:
            started = browser.get(
                "/oauth/v2/authorize",
                params={
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
            )
        request_id = kit.query_value(str(started.headers.get("location", "")), "authRequest")
        if not request_id:
            found["trouble"] = (
                "the authorize endpoint did not answer a v2 auth request for a client that "
                "declares loginVersion — M1 is the item that says why"
            )
            return found

        finished = zitadel.finalize_auth_request(
            request_id=request_id, session_id=session_id, session_token=session_token
        )
        callback = str(finished.body.get("callbackUrl", ""))
        code = kit.query_value(callback, "code")
        if not finished.ok or not code:
            found["trouble"] = (
                f"the finalize answered {finished.status} "
                f"{finished.error_id or finished.text[:120]!r} — M2 is the item that says "
                "whether this credential may make one at all"
            )
            return found

        with zitadel._client() as browser:
            exchanged = browser.post(
                "/oauth/v2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "code_verifier": verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if exchanged.status_code != 200:
            found["trouble"] = (
                f"the token exchange answered {exchanged.status_code} "
                f"{exchanged.text[:160]!r}, so there is no id_token to read a subject off"
            )
            return found
        id_token = str(dict(exchanged.json()).get("id_token", ""))
        if not id_token:
            found["trouble"] = (
                "the token exchange answered 200 with no `id_token` — the hosted door's "
                "whole subject comes out of that token, so nothing is asserted here"
            )
            return found
        found["token_subject"] = _unverified_subject(id_token)
        return found
    finally:
        kit.deactivate_application(project_id=project_id, app_id=made.id)


def measure_subject_is_session_user_id(world: World) -> Outcome:
    """**M12** — the two doors answer the same subject, or they do not.

    The fact the whole identity join rests on, and until this row existed it
    was an assumption in a docstring. `record_identity` keys the identity
    join on ONE string per realm, the subject, and two doors write it down two
    different roads: the hosted page comes back through allauth carrying an id_token's
    `sub`, and this deployment's own form reads `factors.user.id` off a
    Session API answer. If this build ever stopped making those the same
    string, a person who used one door on Monday and the other on Tuesday
    would meet `Conflict` — *That identity is already linked to a different
    account* — at their own account, and nothing in the suite could see it:
    the two fakes would go on agreeing with each other.

    **No id_token is `could not`, never an `ok`.** A journey that did not
    reach a token has measured nothing at all, and the kit's grammar puts that
    above a disagreement (exit 2) rather than below it.
    """
    seen = _one_person_through_both_doors(world)
    if seen.get("trouble"):
        return could_not(str(seen["trouble"]))
    ours = str(seen.get("session_user_id", ""))
    hosted = str(seen.get("token_subject", ""))
    if not ours:
        return could_not(
            "the session read carries no `factors.user.id`, so our door's half of the "
            f"comparison does not exist (factors={seen.get('factors')})"
        )
    if not hosted:
        return could_not(
            "the id_token carries no `sub` claim, so the hosted door's half of the "
            "comparison does not exist"
        )
    if ours != hosted:
        return differs(
            f"the session reports factors.user.id={ours!r} and the id_token minted for "
            f"that same session carries sub={hosted!r} — the two doors no longer name one "
            "person with one string, and `record_identity` would refuse the second "
            "door with `Conflict` at an account its owner is standing in front of"
        )
    return ok(
        f"one session, both doors: factors={seen.get('factors')}, our door reads "
        f"factors.user.id={ours!r} and the id_token finalized against that same session "
        f"carries sub={hosted!r} — byte-identical, so a person who signs in through the "
        "hosted page and then through ours is ONE identity fact"
    )


def measure_reset_landing(world: World) -> Outcome:
    """**M6** — where the password-reset mail's link lands, application on login v2.

    The finding, and it is WATCH F6's class again for a second journey: the
    mail's link is the identity platform's own `password/init` page and the
    per-application `loginVersion` does not move it. A mail has no application
    context — the link Zitadel composes carries an EMPTY `authRequestID` — so
    a deployment on `ours` that offers *Forgot your password?* sends a person
    to a screen it does not own.

    **The link is reconstructed, not read out of an inbox.** `returnCode`
    hands the code straight back, and the four parameters are the ones
    Zitadel's own mail carries: hand-observed on 2026-09-19 against the
    pinned build, through a real mail sink, as

        <issuer>/ui/login/password/init?authRequestID=&code=<six>&orgID=<org>&userID=<id>

    — and this measurement mints its own code and fetches exactly that shape.
    What it therefore does NOT cover is the mail BODY: a build that changed
    the template's link while still serving this path would pass here, and
    `blind_spots()` says so.
    """
    minted = zitadel.probe(
        "POST", f"/users/{world.user_id}/password_reset", {"returnCode": {}}, prefix=zitadel.USER
    )
    if not minted.ok:
        return could_not(
            f"POST /v2/users/{{id}}/password_reset answered {minted.status} "
            f"{minted.error_id or minted.text[:120]!r}, so there is no reset road to follow"
        )
    code = str(minted.body.get("verificationCode", ""))
    if not code:
        return differs(
            "the reset answered 200 with no `verificationCode`, so `returnCode` was not "
            "honoured and the code this measurement needs is only in an inbox"
        )
    link = f"{RESET_PATH}?authRequestID=&code={code}&orgID={world.org_id}&userID={world.user_id}"
    landed = zitadel.probe("GET", link, prefix="")
    if landed.status in (301, 302, 303, 307, 308):
        return differs(
            f"the reset link answered {landed.status} to "
            f"{landed.body.get('location', '(no Location read)')!r} — it no longer lands "
            "where the mail's own page is"
        )
    if not landed.ok:
        return could_not(f"the reset link answered {landed.status}")
    ours = f"{surface_base_urls()[0]}{LOGIN_BASE_PATH}"
    if RESET_MARK not in landed.text:
        return differs(
            f"{RESET_PATH} answered {landed.status} without the Set Password form "
            f"({RESET_MARK!r} is not in it) — the mail's link no longer lands on a page "
            "that sets a password"
        )
    return ok(
        f"the mail's link lands on the PLATFORM's own {RESET_PATH} ({landed.status}, the Set "
        f"Password form), never on {ours} — the application's loginVersion does not reach a "
        "mail, and its `authRequestID` is empty by construction"
    )


def _judge_sso_after_finalize(seen: Mapping[str, Any]) -> Outcome:
    """**M7** — what the browser is left holding, and what J5 may therefore say.

    `differs` when an SSO session survives, because the sign-out page's
    sentence under `ours` — *This ends your session. Signing back in asks for
    your password again.* — would then be a promise this deployment does not
    keep, and a false sentence on a security screen is the item's whole point.
    """
    if seen.get("sso_trouble"):
        return could_not(str(seen["sso_trouble"]))
    if "sso_code" not in seen:
        return could_not("the round trip did not get far enough to ask a second authorize")
    after = list(seen.get("sso_cookies_after") or [])
    if seen["sso_code"]:
        return differs(
            f"a second authorize with prompt=none answered a CODE — the browser holds an SSO "
            f"session at the platform ({', '.join(after) or 'no cookie this jar can see'}), so "
            "the sign-out page's `ours` sentence about signing back in is not true here"
        )
    landed = "the sign-in page again" if seen.get("sso_sent_to_sign_in") else "no code"
    return ok(
        f"a second authorize with prompt=none answered {landed}"
        f"{' (error=' + str(seen['sso_error']) + ')' if seen.get('sso_error') else ''}; the "
        f"jar holds {', '.join(after) or 'nothing'} — the device cookie and no session, so "
        "J5's `ours` sentence is a measured fact and not an intention"
    )


# --- the run -----------------------------------------------------------------


def measure(world: World) -> dict[str, Outcome]:
    """Every item that can be measured today, in the order Zitadel allows.

    The sequence is not cosmetic and is stated once here rather than implied by
    call order: C3 and C4 need the throwaway org still INHERITING, M10 then
    writes it a policy of its own, M10 mints the invite code while the human is
    still credential-LESS, and only after that does M8 set a password. Reordered,
    three of the five would measure a world that no longer exists.
    """
    outcomes: dict[str, Outcome] = {}

    def run(item_id: str, measurement: Callable[[], Outcome]) -> None:
        try:
            outcomes[item_id] = measurement()
        except zitadel.ZitadelError as error:
            outcomes[item_id] = could_not(str(error))

    run("C1 put-field-sets", measure_field_sets)
    run("C2 invite-code-expiry", measure_invite_expiry)
    run("C5 instance-5m9vdd", measure_instance_5m9vdd)
    run("C6 proto3-zero-omission", measure_proto3_zero_omission)
    run("C7 invite-path", measure_invite_path)
    run("C8 v2-users-human-empty", measure_v2_users_human_empty)
    run("M1 authorize-redirect-per-login-version", measure_authorize_redirect)
    run("M2 finalize-needs-login-client", measure_login_client_role)
    run("C3 is-default", lambda: measure_is_default(world))
    run("C4 org-m0sif", lambda: measure_org_m0sif(world))
    run("M5 session-user-check-is-not-a-password", lambda: measure_session_user_check(world))
    run("M11 org-password-complexity", lambda: measure_password_complexity(world))
    run("M10 invite-ignores-org-default-redirect", lambda: measure_invite_ignores_redirect(world))
    set_password = zitadel.probe(
        "POST",
        f"/users/{world.user_id}/password",
        {"newPassword": {"password": world.password, "changeRequired": False}},
        prefix=zitadel.USER,
        org_id=world.org_id,
    )
    if set_password.ok:
        run("M8 session-patch-rotates-the-token", lambda: measure_session_patch_rotates(world))
    else:
        outcomes["M8 session-patch-rotates-the-token"] = could_not(
            f"the throwaway human could not be given a password "
            f"({set_password.status} {set_password.error_id or set_password.text[:120]!r}), "
            "so there is no factor for a PATCH to verify"
        )
    run("M9 webauthn-no-passkey-is-a-500", lambda: measure_webauthn_no_passkey(world))
    # M3 and M4 last of the world's items: the round trip needs the human to
    # HAVE the password M8's prelude just gave them, and it is the only item
    # that makes an object outside the throwaway organisation.
    run(M6, lambda: measure_reset_landing(world))
    try:
        outcomes |= measure_mode_a(world)
    except zitadel.ZitadelError as error:
        outcomes[M3] = could_not(str(error))
        outcomes[M4] = could_not(str(error))
        outcomes[M7] = could_not(str(error))
    # M12 last: its journey needs the password M8's prelude gave the human,
    # and it is the second item that makes an object outside the throwaway
    # organisation — declared in `blind_spots()` beside M1's.
    run(M12, lambda: measure_subject_is_session_user_id(world))
    for item_id, rung in PROMISED.items():
        outcomes[item_id] = unmeasured(rung, f"the ingredient lands at rung {rung}")
    return outcomes


class Command(BaseCommand):
    help = (
        "Measure the pinned Zitadel against every fact this tree took off it. "
        "Creates and deletes its own throwaway organisation; changes no intent."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        if not zitadel.configured():
            raise CommandError(
                "Zitadel is not configured: ZITADEL_ISSUER and ZITADEL_PAT must both be "
                "set. There is nothing to measure against, and an unmeasured instance is "
                "could-not-look rather than agreement.",
                returncode=2,
            )

        self.stdout.write("version")
        self.stdout.write(f"  compose pin   {compose_pin()}")
        self.stdout.write(f"  issuer        {getattr(settings, 'ZITADEL_ISSUER', '')}")
        for name in ("management", "admin"):
            try:
                info = dict(kit.swagger_document(name=name).get("info") or {})
            except zitadel.ZitadelError as error:
                self.stdout.write(f"  {name:<13} could not read this build's document: {error}")
                continue
            # Verbatim, and no equality asserted (I5.3): the pin above and the
            # document below are two independent statements about which build
            # this is, printed so a reader of a DIFFERS six weeks from now can
            # see which one the disagreement belongs to.
            self.stdout.write(
                f"  {name:<13} {info.get('title', '?')} v{info.get('version', '?')} "
                f"({info.get('license', {}).get('name', '?')})"
            )
        self.stdout.write("")

        world = World()
        try:
            with throwaway(self.stdout, world) as built:
                try:
                    build_world(built)
                except zitadel.ZitadelError as error:
                    outcomes = self._without_a_world(str(error))
                else:
                    outcomes = measure(built)
        except zitadel.ZitadelError as error:
            outcomes = self._without_a_world(str(error))

        self.stdout.write("")
        for item in ITEMS:
            outcome = outcomes[item.id]
            self.stdout.write(f"{outcome.verdict:<19} {item.id} — {item.subject}: {outcome.detail}")
        self.stdout.write("")
        for line in blind_spots():
            self.stdout.write(line)
        self.stdout.write("")

        verdicts = [outcomes[item.id].verdict for item in ITEMS]
        blind = sum(1 for one in verdicts if one == COULD_NOT)
        wrong = sum(1 for one in verdicts if one == DIFFERS)
        later = sum(1 for one in verdicts if one.startswith(UNMEASURED))
        agreed = sum(1 for one in verdicts if one == OK)
        tally = (
            f"{len(ITEMS)} item(s): {agreed} ok, {wrong} DIFFERS, {blind} could not, "
            f"{later} unmeasured."
        )
        if world.left_behind:
            tally += f" LEFT ON THE INSTANCE: organisation {world.left_behind}."
        if blind:
            self.stdout.write(self.style.WARNING(f"{tally} Nothing is asserted about the {blind}."))
            raise SystemExit(2)
        if wrong:
            self.stdout.write(
                self.style.WARNING(
                    f"{tally} This build no longer answers what the tree says it answers."
                )
            )
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(f"{tally} This build answers what the tree says."))

    @staticmethod
    def _without_a_world(reason: str) -> dict[str, Outcome]:
        """Every item `could not`, because the instance would not answer at all.

        Not a partial report. An instrument that measured the six items needing
        no throwaway org and reported the rest as blind would exit 2 either way,
        and the shorter road keeps one failure from being printed twenty
        different ways.
        """
        outcomes = {item.id: could_not(reason) for item in ITEMS}
        for item_id, rung in PROMISED.items():
            outcomes[item_id] = unmeasured(rung, f"the ingredient lands at rung {rung}")
        return outcomes
