"""The sign-in door: `/accounts/login/`, and which of the two doors answers it.

**One view, two doors, and the switch is `SIGN_IN_DOOR`** (design C-13).

* `hosted` — the DEFAULT, and what every deployment has had until now. This
  view hands the request straight to allauth's own `LoginView`, byte for byte:
  the page is the one-button entrance, the POST is still refused (ADR ident-4
  closed the local password store), and none of the machinery below is
  visible to anybody who has not turned the setting.
* `ours` — the product draws the sign-in itself. The frames are design P-10's
  (`templates/account/frames/`), the CHECK is `apps.accounts.signin` — the
  seam, which holds every fail-closed rule — and the COMPLETION is allauth's
  own `complete_social_login`, so `SocialAccountAdapter._platform_login` makes
  exactly the three decisions it makes on the OIDC road and this door decides
  none of them a second time.

**Why this is one `config/urls.py` line ahead of `include("allauth.urls")`
rather than an allauth view subclass** (the lead's decision 16): a
`LoginView` is a Django *form* view, and the thing being mounted here is not a
form — it is a multi-step ceremony whose state lives in the session and whose
verdict is a closed enum. Overriding the form view would mean fighting its
`form_valid`/`form_invalid` shape on every step. The shadow is the same
pattern `/admin/login/` already uses one mount above (ADR ident-4), for the
same reason and with the same property: allauth still contributes the
`account_login` NAME, which still reverses to this path, and what changed is
only which callable answers it.

**The whole of J2, at A6: password → factor → landed, or password →
enrolment → landed.** Three frames, one URL, one server-side ceremony. The
door's job across them is narrow and worth stating, because everything it is
NOT doing is a rule of the seam's that it must not re-decide: it turns one
`SignIn` into one frame, it draws the chips the seam handed it (never a kind
it thought of itself), and it says the sentence the outcome names.

**A kind this deployment cannot answer is still a dead end with a sentence**,
never a hand-off to the hosted page — under login v2 that is a 302 loop and it
is what locked an owner out of the consumer's deployment for a morning (their
K10). What A6 changed is the POPULATION: at A5 every kind landed there
because no factor road existed; now the kinds the seam can ask for and this
instance can deliver (`signin.deliverable`) reach a form, and only the rest
read the sentence.

**Two things the door keeps that the ceremony deliberately does not.** The
`?next=` the person arrived with, and the login name they typed — both in
this door's own session keys, both taken ONCE at the start, and both read
back at the landing. `?next=` is taken once because a proven password must
not be able to re-point where it lands (the consumer's NO-GO V-184): a second
request carrying a different `?next=` is ignored, not honoured. The typed
name is kept because `signin.asserted_person` reads the platform's record by
login name and the code form has no address field on it.

**Nothing here talks to Zitadel.** House rule 27: the seam is the one
request-path importer of `apps.accounts.zitadel`, and this module imports the
seam. A read the door needs that the CHECK does not produce — the platform's
own record of the person, which is where `verified` comes from — is
`signin.asserted_person`, on the far side of that seam and not here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote, urlsplit

from allauth.account import views as allauth_account_views
from allauth.account.utils import get_next_redirect_url
from allauth.socialaccount.adapter import get_adapter as get_socialaccount_adapter
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialLogin
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from apps.accounts import qr, signin
from apps.accounts.selectors import get_platform_provider_id
from apps.core.log import get_logger

log = get_logger(__name__)

__all__ = ["CHIP_LABELS", "FRAME_TITLES", "LEDES", "SENTENCES", "sign_in"]

#: The door this module answers as when `SIGN_IN_DOOR` names it. A constant
#: rather than the literal at the branch, so the one comparison in this file
#: cannot drift from the one `zitadel_seed` makes.
OURS = "ours"

#: The page `<title>` each frame gets. **A5's rider**: A4 shipped the six
#: frames under one `<title>Sign In</title>` — the shell's default — so a
#: person with four tabs open could not tell the enrolment screen from the
#: sign-in one, and neither could a screen reader announcing the document.
#:
#: The door picks it WITH the frame, because the door is what knows which
#: frame it is drawing; the template's `head_title` block falls back to
#: today's words when nothing is handed in, which is what keeps `hosted`
#: byte-identical. The keys are censused against the frames directory
#: (`test_signin_door.py`), so a seventh frame is a failure here rather than a
#: title somebody has to remember.
FRAME_TITLES: Mapping[str, str] = {
    "sign_in": "Sign in",
    "one_more_step": "One more step",
    "set_up_two_factor": "Set up two-factor",
    # The NAME of a frame and a page title, not a credential.
    "choose_your_password": "Choose your password",  # pragma: allowlist secret
    "reset": "Reset your password",  # pragma: allowlist secret
    "signed_out": "Signed out",
    # The SEVENTH, and the one frame in the vocabulary with no form on it
    # (design J7's `request_gone`): there is nothing here to finish, so a
    # form would be an act that cannot land. A11 added it; A8 had been
    # answering that state on the sign-in frame, which is the "must not"
    # column's own example — *render the form as if a plain sign-in would
    # land somewhere useful*.
    "link_expired": "This link has expired",
}

#: Design J7's first line, per outcome. The STANDING SECOND LINE — *If this
#: keeps happening, ask whoever runs your organization to reset your sign-in.*
#: — is not here: it is in the frame's own alert slot
#: (`templates/account/frames/sign_in.html`), printed on every note, which is
#: what keeps a locked person's road out on the screen without a "locked"
#: sentence existing anywhere. A distinct locked sentence is an oracle over
#: which addresses exist and have been attacked (J7), so `refused` is one
#: sentence for a wrong password, an unknown address and a locked account.
SENTENCES: Mapping[signin.SignInOutcome, str] = {
    signin.SignInOutcome.REFUSED: "That email and password don't match. Try again.",
    signin.SignInOutcome.THROTTLED: "Too many tries. Wait a minute and try again.",
    signin.SignInOutcome.UNAVAILABLE: (
        "We couldn't reach the sign-in service. Try again in a moment."
    ),
    signin.SignInOutcome.CEREMONY_GONE: "That took too long. Start again.",
    signin.SignInOutcome.CANCELLED: (
        "You stopped before finishing, so you are not signed in and nothing was changed."
    ),
    # Design J7's three for frame J1-a. `invite_gone` is ONE sentence for a
    # code that was used, one that expired and one a later mint superseded,
    # because Zitadel answers one error id for all three (measured) — and
    # because the remedy is the same in every case and it is the whole of what
    # the person can do. `invite_weak` is completed at the call site with the
    # policy's own reason; the entry here is the fallback for a refusal that
    # carried no readable one.
    signin.SignInOutcome.INVITE_GONE: (
        "This link has already been used or has expired. Ask whoever invited you for a fresh one."
    ),
    signin.SignInOutcome.INVITE_WEAK: "That password doesn't meet the rules.",
    signin.SignInOutcome.INVITE_REFUSED: "This link was already used. Sign in instead.",
    # Mode A (design J7's `request_gone`). One sentence for an auth request
    # that expired, one that was already answered and one that never existed,
    # because from where the person stands the three are one fact and the
    # move is the same. It names the APP rather than this product: they did
    # not come here on purpose and "try again" here would land them
    # somewhere the app they were using cannot see.
    #
    # **It is not passed to a page as a note, and it is not dead either.**
    # This state's frame carries no form (A11's seventh), so its words are
    # the frame's own h1 and lede rather than an alert over a form — and
    # this entry is the one place the sentence is written down, which
    # `test_every_frame_sentence_matches_the_design` reads the frame against.
    signin.SignInOutcome.REQUEST_GONE: (
        "This sign-in link has expired. Go back to the app that sent you here and try again."
    ),
}

#: Design J7's `kind_unanswerable` row, one sentence per kind, each ending
#: BEFORE the standing remedy the frame prints. Never "MFA", "2FA", "U2F" or
#: "WebAuthn" on any face — the design's "must not" column.
#:
#: **At A5 every kind landed here**, because the factor road was A6's. It is
#: now narrowed by `signin.deliverable` to the kinds that genuinely cannot be
#: delivered — an emailed code on an instance with no SMTP sender, a texted
#: code nothing here can promise, a key or a passkey whose browser ceremony
#: is design J6 — and the words are true of exactly those. The sentences did
#: not move: "right now" and "yet" were already the honest tense for a thing
#: this deployment cannot do today, and a reader comparing A5's page with
#: A6's sees the same sentence for the same reason.
KIND_SENTENCES: Mapping[str, str] = {
    signin.FactorKind.OTP_EMAIL: (
        "This account signs in with an emailed code, and we can't send one right now."
    ),
    signin.FactorKind.OTP_SMS: (
        "This account signs in with a texted code, and we can't send one right now."
    ),
    signin.FactorKind.TOTP: (
        "This account signs in with a code from an app, and we can't ask for one right now."
    ),
    signin.FactorKind.U2F: (
        "This account signs in with a security key, and we can't ask for one here yet."
    ),
    signin.FactorKind.PASSKEY: (
        "This account signs in with a passkey, and we can't ask for one here yet."
    ),
}

#: Said when Zitadel reports a kind outside the seam's closed five. Naming it
#: would put a string Zitadel chose into a page, which is the whole reason the
#: seam answers `unknown_kind` rather than the name.
#: **The standing remedy is the FRAME's and is printed on every note**, so a
#: sentence here must not end with it too. V-A-W3 read both on one screen —
#: "…reset your sign-in." followed by "If this keeps happening, ask whoever
#: runs your organization to reset your sign-in." — which is the page saying
#: the same thing twice in two voices.
_AN_UNKNOWN_KIND = "This account signs in a way this page can't ask for."

#: **Design J7 has one `refused` row and it is about a password.** A wrong
#: six-digit code needs its own words for the same reason the password row
#: exists at all: "That email and password don't match" on a screen with
#: neither field on it tells the person to go and check something they are
#: not looking at. The standing remedy line rides underneath it exactly as it
#: does on every other refusal, so a person whose authenticator has drifted
#: still reads their road out. Reported as a lexicon addition.
A_REFUSED_CODE = "That code isn't right. Try again."

#: Said when *Not now* is pressed and the platform refuses it — the org's
#: login settings changed between the render that drew the link and the press
#: that used it. Never silently honoured: the customer's policy is the
#: customer's, and a template that let a stale button overrule it would be
#: the product deciding a deployment's security posture. Reported as a
#: lexicon addition.
A_REFUSED_SKIP = "Your organization asks for the second step now. Set one up to carry on."

#: Design J6's own sentence, in the tree's own ending. The design writes
#: *"…Add one from Your account on a device you're signed in on"* and then
#: says that on OUR tree there is no account page (unproven ingredient P-11),
#: so the sentence ends at the remedy instead. Taken verbatim from that
#: instruction rather than improved.
#:
#: **Reachable because of a measurement, not a guess.** A9's drive found that
#: a passkey bound elsewhere and no passkey at all answer the SAME `500
#: WEBAU-4G8sw`, so the seam tells them apart from `authentication_methods`
#: and this sentence is said only to somebody who really does own one.
#: Design J6 writes *"…Add one from Your account on a device you're signed in
#: on"* and then says that on OUR tree there is no account page, so the
#: sentence ends at the remedy instead. It ends BEFORE the remedy here: the
#: frame prints that line under every note already, and V-A-W3 read it twice
#: on one screen.
A_PASSKEY_FROM_SOMEWHERE_ELSE = "Passkeys added elsewhere don't work here."

#: A person with no passkey at all who presses the passkey button. **Not
#: `KIND_SENTENCES[PASSKEY]`** — "this account signs in with a passkey" is
#: simply false of them, and V-A-W3 read it on a person who had never
#: registered one.
A_PASSKEY_NOBODY_HAS = "There's no passkey on this account. Sign in with your password."

#: The lede under the `h1` at `Step.FACTOR`, per kind. One word per kind,
#: shared with `CHIP_LABELS` and with `KIND_SENTENCES`, so the page never
#: calls one thing two names (the consumer's V-LOGIN-ALL-1 rider).
LEDES: Mapping[str, str] = {
    signin.FactorKind.TOTP: "Enter the code from your authenticator app.",
    signin.FactorKind.OTP_EMAIL: "Enter the code we emailed you.",
    signin.FactorKind.OTP_SMS: "Enter the code we texted you.",
    signin.FactorKind.U2F: "Use your security key to finish signing in.",
    signin.FactorKind.PASSKEY: "Use your passkey to finish signing in.",
}

#: The chooser chips of design J2-b, per kind. The chip a person is ALREADY
#: answering is never drawn — a button that says what the form above it says
#: is a button nobody can act on — so this map is read for the alternatives
#: only.
CHIP_LABELS: Mapping[str, str] = {
    signin.FactorKind.TOTP: "Use a code from my app instead",
    signin.FactorKind.OTP_EMAIL: "Email me a code instead",
    signin.FactorKind.OTP_SMS: "Text me a code instead",
    signin.FactorKind.U2F: "Use my security key",
    signin.FactorKind.PASSKEY: "Use my passkey",
}

#: **How many digits each kind's code actually has, MEASURED.** A TOTP code
#: is six; Zitadel's emailed code is **EIGHT** (`Your sign-in code is
#: 41470160`, V-A-W3's Mailpit capture). The frame shipped `maxlength="6"`
#: for both, so the browser truncated every emailed code to six characters
#: and the platform refused it — and the same code pasted past the cap
#: landed. A page must never cap a field shorter than the value the platform
#: sends: the cap is a fact about the kind, not a decoration.
CODE_LENGTHS: Mapping[str, int] = {
    signin.FactorKind.TOTP: 6,
    signin.FactorKind.OTP_EMAIL: 8,
    signin.FactorKind.OTP_SMS: 8,
    # The WebAuthn kinds have no typed code at all; the length is never read
    # for them and is here so the map is the closed set.
    signin.FactorKind.U2F: 0,
    signin.FactorKind.PASSKEY: 0,
}

#: Which kind the door asks for first when a person has several. An
#: authenticator app is already showing a code, so it costs no round trip and
#: no waiting; a mailed code costs both. The order is the door's, not the
#: platform's: `authentication_methods` answers in whatever order it likes
#: and a page that followed it would ask different people different things
#: for no reason a person could see.
PREFERRED: tuple[signin.FactorKind, ...] = (
    signin.FactorKind.TOTP,
    signin.FactorKind.OTP_EMAIL,
    signin.FactorKind.OTP_SMS,
    signin.FactorKind.U2F,
    signin.FactorKind.PASSKEY,
)

#: The form field that says which road a POST is taking. A closed set, and an
#: unknown value is a 400 rather than a re-rendered form: a page that answered
#: a typo'd action with the sign-in screen would look like a refusal and be a
#: bug, and there is no browser road that sends one.
PASSWORD_ACTION = "password"  # pragma: allowlist secret
CODE_ACTION = "code"
#: Design J6's two. `passkey_start` is the affordance on J2-a — an address
#: and a passkey, no password; `passkey` carries the assertion the browser
#: produced, on whichever frame the ceremony began on.
PASSKEY_START_ACTION = "passkey_start"
PASSKEY_ACTION = "passkey"
ENROL_ACTION = "enrol"
CANCEL_ACTION = "cancel"
SKIP_ACTION = "skip"

#: A chip's action is its kind with this in front. Derived rather than a
#: sixth table, so a kind cannot have a chip the door does not recognise or
#: an action no chip draws.
CHIP_ACTION_PREFIX = "use_"

#: **Two facts this door keeps for the length of a ceremony, in its own keys.**
#: Neither belongs in `signin.CEREMONY_FIELDS`: the seam knows nothing about
#: where a person lands, and it deliberately never stores the address (its
#: log sweep is the census that says so). They are server-side session keys
#: for the same reason the ceremony is — a hidden form field carrying either
#: one is a field a second POST can rewrite.
NEXT_KEY = "accounts.signin.next"
TYPED_KEY = "accounts.signin.typed"

#: The Choose-your-password frame's own action (design J1-a). A second member
#: of that closed set rather than a second view, because it is the same door
#: at the same address: `invite_url` under `ours` points at `account_login`
#: with the platform's own query on it, and a person who lands there is
#: standing at the sign-in page holding a link.
INVITE_ACTION = "invite"

#: The reset frame's own action, and the query the sign-in frame's *Forgot
#: your password?* link carries (design J5; rung A11b). A query rather than a
#: second URL for `INVITE_ACTION`'s reason: it is the same door at the same
#: address, and a person who lands on it with a `?next=` keeps it.
RESET_ACTION = "reset"  # pragma: allowlist secret
RESET_PARAM = "forgot"

#: The two query parameters Zitadel mints into an invitation link, in
#: Zitadel's own spelling — `invite_url` keeps that tail deliberately (A5.5)
#: so an operator comparing the two doors' links sees one shape.
INVITE_USER_PARAM = "userID"
INVITE_CODE_PARAM = "code"

#: Mode A's own (design C-10, rung A8). The platform composes this when an
#: application declares login v2: the authorize endpoint answers
#: `302 {baseUri}/login?authRequest=V2_…` — MEASURED — so the name is the
#: platform's and not a choice of ours.
AUTH_REQUEST_PARAM = "authRequest"

#: Design J7's `no_sign_up`. An OIDC client may ask for a registration screen
#: (`prompt=create`, which the auth request reports as `PROMPT_CREATE`); there
#: is no sign-up door in this product and there never was (ADR accounts-1), so
#: the page says how people actually arrive instead of drawing a form that
#: leads nowhere. The sign-in form stays under it — somebody who WAS invited
#: can finish right here.
_NO_SIGN_UP = "People arrive here by invitation. Sign in with the address you were invited at."


def sign_in(request: HttpRequest) -> HttpResponse:
    """`/accounts/login/`. Today's page, or ours, and `SIGN_IN_DOOR` decides.

    Unauthenticated by construction: it is the page somebody reaches BEFORE
    they have a credential, and it is recorded in `quality/rules.yaml` under
    rule 3's `allow_unauthenticated_views` with that reason. It writes no row
    of ours; the only writer on the road is `complete_social_login`, through
    the adapter and the services it calls.
    """
    if str(getattr(settings, "SIGN_IN_DOOR", "hosted")) != OURS:
        # **Byte-identical, and that is a criterion rather than a courtesy.**
        # The call is allauth's own view function, so the page, the context,
        # the template and the 403 on a POST are the ones this deployment
        # already serves; nothing here re-implements any of them.
        # `cast` because allauth's view callables are untyped: the object is
        # an `HttpResponse` at runtime and mypy --strict will not take that on
        # trust. Narrowing here rather than loosening the signature.
        return cast(HttpResponse, allauth_account_views.login(request))

    if request.method != "POST":
        # `user_id` and not the pair: a 2-tuple is truthy whatever is in it,
        # and `mypy --strict` said so — `if _invite_link(request)` made the
        # ordinary sign-in page unreachable and every GET an invite.
        #
        # And the second name is `_link_code`, not `_code`: A6's factor road
        # has a MODULE-LEVEL `_code`, and unpacking into that name here made
        # it a local `str` for the whole function — so the dispatch two
        # screens down called a string. `mypy --strict` caught it the moment
        # the two chains were folded together; nothing else would have, short
        # of somebody typing six digits.
        invited, _link_code = _invite_link(request)
        if invited:
            return _invited(request)
        if _auth_request(request):
            return _mode_a(request)
        if request.GET.get(RESET_PARAM):
            # Taken on the GET as well, because somebody may arrive straight
            # at `?next=…&forgot=1` from a bookmark and never see the
            # sign-in form on the way in.
            _remember_next(request)
            return _reset(request)
        return _page(request)

    action = str(request.POST.get("action", ""))
    if action == INVITE_ACTION:
        return _invite(request)
    if action == RESET_ACTION:
        return _request_reset(request)
    if action == PASSWORD_ACTION:
        return _password(request)
    if action == CODE_ACTION:
        return _code(request)
    if action == PASSKEY_START_ACTION:
        return _passkey_start(request)
    if action == PASSKEY_ACTION:
        return _passkey(request)
    if action == ENROL_ACTION:
        return _confirm_enrolment(request)
    if action == CANCEL_ACTION:
        return _cancel(request)
    if action == SKIP_ACTION:
        return _skip(request)
    if action.startswith(CHIP_ACTION_PREFIX):
        return _choose(request, action.removeprefix(CHIP_ACTION_PREFIX))
    log.info("accounts.signin.refused", reason="unknown_action")
    return HttpResponse(
        "This form was submitted with an action this page does not have.",
        status=400,
        content_type="text/plain; charset=utf-8",
    )


# --- the password road (design J2-a) -----------------------------------------


def _password(request: HttpRequest) -> HttpResponse:
    """One address and one password, checked, and whatever is left after it."""
    address = str(request.POST.get("email", "")).strip()
    secret = str(request.POST.get("password", ""))
    # **Both taken here and nowhere else.** This is the one request in the
    # ceremony where the person has not yet proved anything, so it is the one
    # request whose `?next=` is a deep link they chose rather than one a later
    # POST could substitute (V-184). The typed name is kept for the landing's
    # read, which happens on a request that has no address field on it.
    _remember_next(request)
    request.session[TYPED_KEY] = address

    checked = signin.begin(
        request.session,
        address=address,
        password=secret,
        # Mode A: the journey this ceremony is finishing, if it is finishing
        # one. Read off the query on every POST rather than carried in a
        # hidden field: the frames post to the address they are on, so the
        # platform's own parameter rides along, and a hidden input would be a
        # second copy of it for a page to get wrong.
        auth_request=_auth_request(request),
        client_address=_client_address(request),
    )

    return _answer(request, checked, email=address)


# --- the factor road (design J2-b) -------------------------------------------


def _code(request: HttpRequest) -> HttpResponse:
    """The six digits, against whichever kind the ceremony is waiting on."""
    return _answer(request, signin.answer(request.session, code=_code_typed(request)))


def _client_address(request: HttpRequest) -> str:
    """Which caller this is, for the throttle's second bucket. **One site.**

    Read here and nowhere else, so there is one spelling however many roads
    take the throttle — the password one, and now the passkey one.
    """
    # rule-40: `REMOTE_ADDR` is not a header. It is the WSGI/ASGI environ key
    # the SERVER writes from the socket it accepted, and no client sends it
    # or can — which is exactly why the per-client half of the sign-in
    # throttle is bucketed on it rather than on anything a caller walking a
    # thousand addresses could choose. A `*_HEADER` constant and a
    # `CORS_ALLOW_HEADERS` entry would both be claims that a browser is
    # supposed to send it, and neither is true.
    return str(request.META.get("REMOTE_ADDR", "") or "")


def _passkey_start(request: HttpRequest) -> HttpResponse:
    """Design J6 entrance (a): the address, then the device. **No password.**

    It renders back onto J2-a rather than moving the person to the factor
    frame, because nothing has been asked of them: the challenge goes into
    the page and `static/accounts/signin.js` runs the ceremony in place. A
    screen change here would be a screen change for something the person is
    about to answer with a fingerprint.
    """
    address = str(request.POST.get("email", "")).strip()
    _remember_next(request)
    request.session[TYPED_KEY] = address
    checked = signin.passkey_begin(
        request.session,
        address=address,
        client_address=_client_address(request),
    )
    if checked.outcome is signin.SignInOutcome.CONTINUE and checked.passkey_options:
        return _page(request, email=address, passkey_options=checked.passkey_options)
    return _answer(request, checked, email=address)


def _passkey(request: HttpRequest) -> HttpResponse:
    """The assertion the browser produced, verified. The last hop of J6."""
    return _answer(
        request,
        signin.answer(request.session, assertion=str(request.POST.get("assertion", ""))),
    )


def _choose(request: HttpRequest, kind: str) -> HttpResponse:
    """A chip pressed: ask the platform to put a code where the person can read it.

    The kind is not trusted from the form. `signin.challenge` checks it
    against the population the ceremony recorded, so a typed action, a stale
    tab or a chip for a kind the instance stopped being able to deliver all
    reach the same dead end with a sentence.
    """
    return _answer(request, signin.challenge(request.session, kind=kind))


# --- the enrolment road (design J2-c) ----------------------------------------


def _confirm_enrolment(request: HttpRequest) -> HttpResponse:
    """The six digits the authenticator shows, finishing enrolment."""
    return _answer(request, signin.confirm_enrolment(request.session, code=_code_typed(request)))


def _skip(request: HttpRequest) -> HttpResponse:
    """*Not now* — honoured only where the org's own settings allow it."""
    return _answer(request, signin.skip_enrolment(request.session))


def _cancel(request: HttpRequest) -> HttpResponse:
    """*Never mind.* The ceremony ends and the page says nothing was changed."""
    return _answer(request, signin.cancel(request.session))


# --- one verdict, one frame ---------------------------------------------------


def _answer(
    request: HttpRequest, checked: signin.SignIn, *, email: str = "", login_name: str = ""
) -> HttpResponse:
    """The whole switch, in one place, over the seam's two closed vocabularies.

    **`outcome` says what happened and `step` says what to draw**, and this
    function is the only thing in the tree that reads them together. Written
    as one switch rather than one per road because the roads answer the same
    verdicts: a ceremony that timed out looks the same whether the person was
    typing a code or scanning a symbol, and three copies of that arm is three
    places for the sentence to drift.
    """
    if checked.outcome is signin.SignInOutcome.DONE:
        # **Mode A lands somewhere else, and that is the whole difference.**
        # Without an auth request `done` is a session on this product; with
        # one it is a code for the app that sent them, and a door that signed
        # them in here instead would leave that app waiting for ever.
        if checked.callback_url:
            return _back_to_the_app(request, checked.callback_url)
        # `login_name` is the invite road's: the person never typed an
        # address, so the one the platform answered for the user id in their
        # link is what the assertion is built from.
        return _land(request, checked, login_name=login_name)
    if checked.outcome is signin.SignInOutcome.KIND_UNANSWERABLE:
        # **A dead end in Mode A is somebody else's journey ending too.** The
        # app that sent them is waiting on a callback it will never get, so
        # it is told — `ERROR_REASON_ACCESS_DENIED`, M4's enum spelling — and
        # the person goes back to it rather than being left on a page inside
        # a window the app may not own. Outside Mode A there is nobody to
        # tell and the sentence is the whole answer.
        told = _tell_the_client(request, reason=checked.reason)
        if told is not None:
            return told
        return _restart(request, note=_kind_sentence(checked.reason), email=email)
    if checked.outcome is signin.SignInOutcome.REQUEST_GONE:
        return _link_expired(request)
    if checked.outcome is signin.SignInOutcome.CONTINUE:
        if checked.step is signin.Step.ENROL:
            return _begin_enrolment(request, checked)
        return _factor(request, checked)
    if checked.outcome is signin.SignInOutcome.CANCELLED:
        # *Never mind* is the other terminal refusal, and the same reasoning.
        told = _tell_the_client(request, reason="cancelled")
        if told is not None:
            return told
    if checked.reason == "skip_not_offered":
        # **The org's settings moved between the render and the press.** The
        # link was drawn because a skip was allowed and the platform now says
        # it is not, so there is nothing to re-draw: the ceremony ends and the
        # next one begins under the policy that is actually in force. The
        # ceremony is closed through the seam rather than abandoned, for the
        # reason ADR ident-10 gives — every session it opens, it closes.
        signin.cancel(request.session)
        return _restart(request, note=A_REFUSED_SKIP)

    note = _sentence(checked)
    if checked.outcome is signin.SignInOutcome.REFUSED and checked.step is signin.Step.FACTOR:
        # The ceremony is still alive — the platform judged six digits, not
        # the session — so the form the person is looking at stays on the
        # screen with its chips, and the next code is one field away. WATCH
        # F8 is the defect this arm exists to not repeat one screen later.
        return _factor(request, checked, note=note)
    if checked.outcome is signin.SignInOutcome.REFUSED and checked.step is signin.Step.ENROL:
        return _enrolment(request, checked, note=note)
    return _restart(request, note=note, email=email, status=_status_for(checked.outcome))


def _factor(request: HttpRequest, checked: signin.SignIn, *, note: str = "") -> HttpResponse:
    """Frame J2-b, drawn from what the ceremony is offering right now.

    **Both halves come out of the ceremony, never out of the verdict.** The
    population is what `deliverable` intersected and wrote there; the kind
    being asked for is what the last `challenge` recorded. A re-render that
    took either from the `SignIn` in hand would lose the chips on a refused
    code (a refusal carries no kinds) and would flip a person who had chosen
    the emailed road back to the app they do not have open.
    """
    offered = signin.offered(request.session) or checked.kinds
    asking = signin.asked_for(request.session) or _asking(offered)
    chips = [
        {"action": f"{CHIP_ACTION_PREFIX}{one.value}", "label": CHIP_LABELS[one]}
        for one in PREFERRED
        if one in offered and one is not asking
    ]
    return _page(
        request,
        frame="one_more_step",
        note=note,
        lede=LEDES.get(asking, "") if asking is not None else "",
        # **Only on the face that is waiting for mail.** The note tells a
        # person whose name the code will arrive under; on the
        # authenticator-app face there is no mail and no sender, and it
        # rendered there anyway (V-A-W3F). The kind being ASKED decides it,
        # not whether the deployment happens to have a foreign sender.
        sender=checked.foreign_sender if asking is signin.FactorKind.OTP_EMAIL else "",
        chips=chips,
        **_code_field(asking),
        passkey_options=checked.passkey_options,
    )


def _asking(offered: tuple[signin.FactorKind, ...]) -> signin.FactorKind | None:
    """Which of the offered kinds this render is asking for."""
    if len(offered) == 1:
        return offered[0]
    for kind in PREFERRED:
        if kind in offered:
            return kind
    return None


def _begin_enrolment(request: HttpRequest, checked: signin.SignIn) -> HttpResponse:
    """`_after_password` says the org asks for a second step; this asks for one.

    Two shapes arrive here. The verdict off the password road carries the
    POLICY and no secret — nothing has been enrolled yet — so the enrolment
    is begun and its answer is what gets drawn. The verdict off
    `signin.enrol` already carries the URI, and beginning a second one would
    hand the person a second secret and invalidate the symbol they are
    looking at.
    """
    if checked.enrolment_uri:
        return _enrolment(request, checked)
    begun = signin.enrol(request.session)
    if begun.outcome is signin.SignInOutcome.CONTINUE:
        return _enrolment(request, begun)
    return _answer(request, begun)


def _enrolment(request: HttpRequest, checked: signin.SignIn, *, note: str = "") -> HttpResponse:
    """Frame J2-c, with the symbol drawn here and the secret printed beside it.

    **The symbol is drawn only where there is a URI to draw.** A re-render
    after a refused code carries none — the seam begins ONE enrolment and the
    person's authenticator already holds it, so asking the platform for a
    second secret would replace the one they just scanned. The frame draws no
    figure when it is handed none, and the lede says what to do instead.
    """
    drawn = qr.svg(checked.enrolment_uri) if checked.enrolment_uri else ""
    return _page(
        request,
        frame="set_up_two_factor",
        note=note,
        lede="" if drawn else "Type the next code your authenticator app shows.",
        qr=drawn,
        **_code_field(signin.FactorKind.TOTP),
        secret=checked.enrolment_secret,
        skip_days=checked.skip_days if checked.may_skip else 0,
    )


def _sentence(checked: signin.SignIn) -> str:
    """Design J7's first line for this verdict. **The step is half the key.**

    A refusal at the password step is a wrong address-and-password; the same
    outcome at the code steps is six wrong digits, and the two need different
    words because they are read on screens with different fields on them.
    """
    if checked.outcome is signin.SignInOutcome.REFUSED and checked.step in (
        signin.Step.FACTOR,
        signin.Step.ENROL,
    ):
        return A_REFUSED_CODE
    return SENTENCES.get(checked.outcome, SENTENCES[signin.SignInOutcome.REFUSED])


def _code_field(kind: signin.FactorKind | None) -> dict[str, Any]:
    """The length and the pattern for the code field, from the KIND.

    Built here rather than written into the frame because the two numbers
    are facts about the platform, not about the markup — and because the
    frame that carried one number for both kinds truncated every emailed
    code to six characters and told the person it was wrong.
    """
    digits = CODE_LENGTHS.get(kind, 0) if kind is not None else 0
    if not digits:
        return {}
    return {"code_length": digits, "code_pattern": f"[0-9]{{{digits}}}"}


def _code_typed(request: HttpRequest) -> str:
    return str(request.POST.get("code", "")).strip()


def _kind_sentence(kind: str) -> str:
    if str(kind) == signin.PASSKEY_ELSEWHERE:
        return A_PASSKEY_FROM_SOMEWHERE_ELSE
    if str(kind) == signin.PASSKEY_NONE:
        return A_PASSKEY_NOBODY_HAS
    return KIND_SENTENCES.get(str(kind), _AN_UNKNOWN_KIND)


def _status_for(outcome: signin.SignInOutcome) -> int:
    """The status a rendered refusal answers with.

    `unavailable` is a **503** because that is what it is (design J7's own
    column): we could not look, the person should come back, and a monitor
    reading 200s would see a sign-in door that is down as a sign-in door that
    is busy. `throttled` is a 429 for the same honesty. Everything else is a
    200 with the form still on it — a wrong password is not an HTTP error, and
    answering one with a 4xx is how a browser's own error page replaces the
    sentence the person needs to read.
    """
    if outcome is signin.SignInOutcome.UNAVAILABLE:
        return 503
    if outcome is signin.SignInOutcome.THROTTLED:
        return 429
    return 200


# --- the reset road (design J5, settled by M6; rung A11b) -------------------
#
# The *Forgot your password?* link finally goes somewhere. What it goes to is
# not what the design drew: M6 measured that the platform's reset mail lands
# on the PLATFORM's own page with an empty `authRequestID`, so a frame of ours
# that took a new password would be a screen nobody can reach. This page takes
# the ADDRESS, asks the platform to send its own mail, and says where that
# mail goes.
#
# **The page is the same page either way.** An address with an account and an
# address without one get the same bytes, and — because a stopwatch is an
# oracle too — `signin.request_reset` holds both roads to one floor. Nothing
# here branches on whether anybody was found, because nothing here is TOLD.


def _reset(
    request: HttpRequest, *, asked: bool = False, note: str = "", status: int = 200
) -> HttpResponse:
    """Frame J5, in one of its two states. **Neither one takes a password.**

    `asked` is the after-state: no form, and the sentence about where the mail
    lands. The address is echoed back only BEFORE — after, the page says "if
    that address has an account" and repeating what was typed beside it would
    be the same non-committal sentence with the subject filled in.
    """
    return _page(
        request,
        frame="reset",
        note=note,
        asked=asked,
        status=status,
        email="" if asked else str(request.POST.get("email", "")).strip(),
        back=_back_to_sign_in(request),
    )


def _request_reset(request: HttpRequest) -> HttpResponse:
    """POST the address: ask the platform, then say the same thing regardless.

    **It does not touch the stored deep link, and that cost a red to get
    right.** `_remember_next` takes one when the request carries one and
    CLEARS it when it does not — which is how V-184 is kept: a later POST
    must not re-point a landing somebody chose at the start.

    The reset frame's form carries no `action`, so a browser submits it to
    the address it is standing on — `?forgot=1`, with whatever `next` came
    with it. Calling the taker here would therefore RE-TAKE the link off
    this POST's own query, which is V-184's shape exactly: the value happens
    to be the same one today because the query is the one the GET arrived
    on, and "happens to be the same" is not a rule. (A form that posted to
    the bare address would hit the other half of the same function and have
    the stored link CLEARED instead — one function, two ways to be wrong.)
    So the reset road reads the store and never writes it, and
    `test_next_survives_the_detour_through_the_reset_road` posts a DIFFERENT
    `next` than the one taken at the GET to prove which of the two wins.
    """
    address = str(request.POST.get("email", "")).strip()
    asked = signin.request_reset(
        request.session,
        address=address,
        client_address=_client_address(request),
    )

    if asked.outcome is signin.SignInOutcome.RESET_ASKED:
        return _reset(request, asked=True)
    # Throttled or unavailable: the reset frame again, with its own sentence
    # and its own status. Both are answers about US — our limit, our reach —
    # and neither says anything about the address.
    return _reset(
        request,
        note=SENTENCES.get(asked.outcome, SENTENCES[signin.SignInOutcome.UNAVAILABLE]),
        status=_status_for(asked.outcome),
    )


def _forgot_link(request: HttpRequest) -> str:
    """`?forgot=1`, plus whatever deep link is already in play.

    Read from the query first and the ceremony store second: on the very
    first GET of the sign-in page nothing has been remembered yet, and on a
    later render the store is what holds it.
    """
    carried = str(get_next_redirect_url(request) or "") or str(
        request.session.get(NEXT_KEY, "") or ""
    )
    tail = f"&next={quote(carried, safe='')}" if carried else ""
    return f"?{RESET_PARAM}=1{tail}"


def _back_to_sign_in(request: HttpRequest) -> str:
    """The sign-in page, carrying the deep link the person arrived with.

    Read out of the ceremony store rather than off this request's query, so a
    `?next=` taken at the sign-in page survives a detour through here — which
    is the same rule `_land` follows, and the same reason: the landing is
    decided where the person chose it, not where they happen to be standing.
    """
    where = reverse("account_login")
    stored = str(request.session.get(NEXT_KEY, "") or "")
    return f"{where}?next={quote(stored, safe='')}" if stored else where


# --- Mode A: the OIDC round trip on our page (design C-10; rung A8) ---------
#
# The person did not come here on purpose. An app sent them: the browser RP
# through allauth, an MCP client on somebody's laptop, anything holding an
# OIDC client id. With `loginVersion` declared on that application (A2, A5)
# the platform's authorize endpoint answers `302 {baseUri}/login?authRequest=
# V2_…` — this page — instead of drawing its own, and what finishes the
# journey is not a session here but a code THERE.
#
# **MEASURED, and it is the one surprise in this road**: the platform
# composes that redirect WITHOUT a trailing slash on `/login`, and our mount
# is `/accounts/login/`. Django's `APPEND_SLASH` answers the 301 and carries
# the query — so the journey works, at the cost of one hop, and
# `test_mode_a_survives_the_platforms_missing_trailing_slash` is what would
# notice a deployment that turned `APPEND_SLASH` off and silently lost every
# OIDC sign-in.


def _auth_request(request: HttpRequest) -> str:
    """The auth request id on this request's query, or `""`."""
    return str(request.GET.get(AUTH_REQUEST_PARAM, "")).strip()


def _mode_a(request: HttpRequest) -> HttpResponse:
    """GET with an auth request: the sign-in frame, told what the app asked for.

    Three things the ordinary page does not do. The journey is checked before
    anything is drawn, because a form on a dead auth request is a form whose
    submission cannot land. A client that asked for a REGISTRATION screen is
    answered with how people actually arrive here rather than with a form
    that does not exist (ADR accounts-1). And a `login_hint` prefills the
    address, because the app already knows who it sent.
    """
    found = signin.auth_request(request_id=_auth_request(request))
    if found.outcome is signin.SignInOutcome.REQUEST_GONE:
        return _link_expired(request)
    if found.outcome is not signin.SignInOutcome.CONTINUE:
        return _page(request, note=SENTENCES[signin.SignInOutcome.UNAVAILABLE], status=503)
    return _page(
        request,
        note=_NO_SIGN_UP if found.wants_sign_up else "",
        email=found.login_hint,
    )


def _tell_the_client(request: HttpRequest, *, reason: str) -> HttpResponse | None:
    """Answer the OIDC client when the person's journey ended without a code.

    `None` when there is nobody to tell — no auth request on the query, or a
    platform that would not take the refusal — and the caller then falls
    through to its own page, which is the right answer for a person who came
    here on their own. A door that returned a 302 to `""` on that branch
    would be a redirect to this page with nothing said.

    Only the TERMINAL refusals reach here: a dead end and a *Never mind*. A
    wrong password does not — it is retryable, the ceremony survives it, and
    ending the journey would burn one the person was a keystroke from
    finishing.
    """
    request_id = _auth_request(request)
    if not request_id:
        return None
    answered = signin.refuse(request.session, request_id=request_id, reason=reason)
    if not answered.callback_url:
        return None
    return _back_to_the_app(request, answered.callback_url)


def _link_expired(request: HttpRequest) -> HttpResponse:
    """Design J7's `request_gone`, on the one frame that carries no form.

    The auth request expired, was already answered, or never existed — three
    platform error ids, one fact a person can act on, and the act is not on
    this page: it is back in the app that sent them. So the frame states it
    and offers nothing, which is the design's "no form" made literal.
    """
    return _page(request, frame="link_expired")


def _back_to_the_app(request: HttpRequest, callback_url: str) -> HttpResponse:
    """302 to where the PLATFORM said, and nowhere else.

    **Not validated against an allow-list of ours, and that is deliberate.**
    This URL is not user input: Zitadel composed it from the redirect URI the
    OIDC client REGISTERED, which is the one place an OAuth redirect target is
    supposed to come from. A second opinion here would be a list that agrees
    with the registration on the day it is written.

    What IS checked is the scheme, and only because Django checks it for us
    with a 500: `HttpResponseRedirect` raises `DisallowedRedirect` for
    anything but http/https/ftp, so a native client registered under a custom
    scheme (`myapp://…`, ordinary on mobile) would take this page down rather
    than refuse. It reads as an outage instead, which is what it is — this
    deployment cannot deliver that client home — and the sentence is one the
    person can act on. A product that needs custom schemes widens
    `allowed_schemes` here and records why.
    """
    if urlsplit(callback_url).scheme not in ("http", "https"):
        log.warning("accounts.signin.unavailable", reason="callback_scheme_unsupported")
        return _page(request, note=SENTENCES[signin.SignInOutcome.UNAVAILABLE], status=503)
    log.info("accounts.signin.finished", outcome="handed_back")
    return HttpResponseRedirect(callback_url)


# --- the invite road (design C-11, J1-a; rung A7) ----------------------------
#
# The first screen of the product for the first person in a deployment, and
# under `ours` the whole of `zitadel_first_admin` step 1. **The landing is the
# PRODUCT**: WATCH F6 measured the hosted road ending
# `302 Location: /ui/console/` — the first human deposited in the identity
# platform's console, which `setup.sh` tells them never to open — and this
# road ends wherever `LOGIN_REDIRECT_URL` points, through the same
# `complete_social_login` the password road uses.


def _invite_link(request: HttpRequest) -> tuple[str, str]:
    """The link's two halves, or two empty strings. **Whole link or nothing.**

    A half link is not a dead invitation, it is somebody at the sign-in page
    with a stray query parameter — so the road opens only on both, and
    everything else is A5's page unchanged.
    """
    user_id = str(request.GET.get(INVITE_USER_PARAM, "")).strip()
    code = str(request.GET.get(INVITE_CODE_PARAM, "")).strip()
    return (user_id, code) if user_id and code else ("", "")


def _invited(request: HttpRequest) -> HttpResponse:
    """GET the link: draw the frame, or say why there is nothing to draw.

    **The three things on this frame are READ, never typed** (the frame's own
    comment, and the design's copy rules): the address off the platform's
    record for the user id in the link, the rule sentence off the org's
    complexity policy, and the deadline off the instance's own code lifetime.
    An `email=` appended to the URL reaches none of them.

    Nothing here spends the code. The verify is single-use (measured), so a
    render that verified would kill the link of anybody who opened their
    email and then hit reload.
    """
    user_id, _link_code = _invite_link(request)
    found = signin.invitation(user_id=user_id)

    if found.outcome is signin.SignInOutcome.INVITE_REFUSED:
        # The sign-in FORM under the sentence, because signing in is the act
        # they can actually do — and with no address on it, per
        # `signin.invitation`'s note about which answers may carry one.
        return _page(request, note=SENTENCES[signin.SignInOutcome.INVITE_REFUSED])
    if found.outcome is signin.SignInOutcome.INVITE_GONE:
        return _page(request, note=SENTENCES[signin.SignInOutcome.INVITE_GONE])
    if found.outcome is not signin.SignInOutcome.CONTINUE:
        return _page(request, note=SENTENCES[signin.SignInOutcome.UNAVAILABLE], status=503)

    return _choose_your_password(request, found)


def _invite(request: HttpRequest) -> HttpResponse:
    """POST the frame: verify, set, sign in, land.

    The link's halves are read off the QUERY and never off the body: the
    frame's form carries no `action=` attribute, so a browser submits it to
    the address it is on, and the code therefore never has to be parked in a
    session store to survive the round trip. A POST that arrives without them
    is a form submitted from nowhere, and it reads the same sentence a dead
    link does — which is what it is.
    """
    user_id, code = _invite_link(request)
    if not user_id:
        return _page(request, note=SENTENCES[signin.SignInOutcome.INVITE_GONE])

    checked = signin.set_invited_password(
        request.session,
        user_id=user_id,
        code=code,
        password=str(request.POST.get("password", "")),
        # rule-40: the server's own socket, never a header — the same reason
        # `_password` bucket the throttle on it.
        client_address=str(request.META.get("REMOTE_ADDR", "") or ""),
    )

    if checked.outcome is signin.SignInOutcome.INVITE_REFUSED:
        return _page(request, note=SENTENCES[signin.SignInOutcome.INVITE_REFUSED])
    if checked.outcome in (
        signin.SignInOutcome.INVITE_GONE,
        signin.SignInOutcome.INVITE_WEAK,
    ):
        # Back to the same frame, still fillable, with the reason on it. The
        # frame is re-read rather than remembered: this render is a fresh GET
        # of the platform's answers, so a policy that changed between the two
        # requests is the policy the sentence states.
        return _choose_your_password(
            request,
            signin.invitation(user_id=user_id),
            note=_invite_note(checked),
        )
    # **Everything else is the ordinary switch**, and since A6 that is a
    # switch that can draw a factor: an invited person whose organisation
    # asks for a second step now sets a password and meets the enrolment
    # frame in one page-load, where A7 alone could only meet a sentence.
    return _answer(request, checked, email=checked.login_name, login_name=checked.login_name)


def _invite_note(checked: signin.SignIn) -> str:
    """The sentence for a refusal on this road. **Never an error id.**

    `invite_weak` is the one sentence in this door completed with a string
    the platform wrote — the org's complexity policy is the platform's, so a
    sentence of ours restating it goes wrong on the first org that tightens
    one. The seam has already stripped the error id (`_policy_reason`); this
    is where the empty case falls back to the plain sentence rather than to a
    colon with nothing after it.
    """
    plain = SENTENCES[checked.outcome]
    if checked.outcome is not signin.SignInOutcome.INVITE_WEAK or not checked.refusal_detail:
        return plain
    return f"{plain[:-1]}: {checked.refusal_detail}."


def _choose_your_password(
    request: HttpRequest, found: signin.Invitation, *, note: str = ""
) -> HttpResponse:
    """Frame J1-a, drawn from what the platform answered and nothing else."""
    return _page(
        request,
        frame="choose_your_password",
        note=note,
        email=found.address,
        password_rule=_password_rule(found.password_rules),
        expires=_expires_on(found.lifetime),
    )


def _password_rule(rules: Mapping[str, Any]) -> str:
    """M11 as a sentence. **No policy handed in, no sentence** (the frame's rule).

    A number typed into the template would be a promise this deployment's
    platform has not made: the first org to tighten its policy would refuse a
    password the page had just told the person was long enough. The shape is
    the one measured on the pinned build — `minLength` arrives as a STRING,
    the four requirements as booleans.
    """
    length = str(rules.get("minLength", "")).strip()
    if not length.isdigit() or int(length) <= 0:
        return ""
    wanted = [
        word
        for key, word in (
            ("requiresUppercase", "an uppercase letter"),
            ("requiresLowercase", "a lowercase letter"),
            ("requiresNumber", "a number"),
            ("requiresSymbol", "a symbol"),
        )
        if rules.get(key)
    ]
    if not wanted:
        return f"At least {int(length)} characters. Nothing else is required."
    listed = wanted[0] if len(wanted) == 1 else f"{', '.join(wanted[:-1])} and {wanted[-1]}"
    return f"At least {int(length)} characters, with {listed}."


def _expires_on(lifetime: timedelta | None) -> str:
    """The deadline as a date somebody can act on, or nothing at all.

    `None` when the instance's secret generator could not be read, and the
    frame then drops the sentence — the same posture the invitation email
    takes (`invite_code_lifetime`'s own docstring): a stated deadline that is
    wrong is worse than no deadline.
    """
    if lifetime is None:
        return ""
    # `%-d` rather than `%d` so it reads "17 September" and not "17 September"
    # with a leading zero, which is how the design's own frame writes it.
    return (datetime.now(tz=UTC) + lifetime).strftime("%-d %B")


# --- landing (the completion is allauth's, deliberately) ----------------------


def _land(request: HttpRequest, checked: signin.SignIn, *, login_name: str = "") -> HttpResponse:
    """The check said yes. **allauth decides whether that becomes a session.**

    This door builds the assertion and hands it over; every rule about what an
    assertion is allowed to do — an unverified address refused with no `User`
    row written, an existing person LINKED rather than duplicated, the subject
    recorded through the one service — is `SocialAccountAdapter`'s, unchanged,
    and is the same code the OIDC road runs. A door that re-implemented any of
    the three would be a second opinion about who may sign in, which is the
    one thing `adapter.py`'s first paragraph exists to prevent.

    **`state` is composed rather than read whole.** `SocialLogin.state_from_
    request` would take `process` off the query string too, and `?process=
    connect` on a sign-in page is somebody else's account being connected to
    this assertion. So the `next` is allauth's — `get_next_redirect_url`, which
    drops a URL that is not same-origin, and is why a foreign `?next=` lands at
    `LOGIN_REDIRECT_URL` instead — and the process is pinned to `login` here.
    """
    typed = login_name or _typed(request)
    person = signin.asserted_person(subject=checked.subject, login_name=typed)
    provider = _platform_provider(request)
    if person is None or provider is None:
        return _restart(
            request,
            note=SENTENCES[signin.SignInOutcome.UNAVAILABLE],
            email=typed,
            status=503,
        )

    # **Built by the PROVIDER, from claims, and not by hand.** This is the
    # same call the OIDC callback makes (`sociallogin_from_response`), so the
    # subject comes out of `extract_uid`, the address and its verified flag
    # out of `extract_email_addresses`, and the adapter downstream is handed
    # an object of exactly the shape it already judges. A door that assembled
    # a `SocialLogin` itself would be a second extractor, and the first field
    # it spelled differently would be a rule of `_platform_login`'s quietly
    # reading something else.
    sociallogin = provider.sociallogin_from_response(
        request,
        {
            "sub": person.subject,
            "email": person.address,
            "email_verified": person.verified,
        },
    )
    state = SocialLogin.state_from_request(request)
    state["process"] = "login"
    # **The landing was decided before the password was proven** (V-184).
    # `state_from_request` reads `?next=` off THIS request, and this request
    # can be the third POST of a ceremony — so whatever it found is replaced
    # by what the first one did, and by nothing at all when the first one had
    # none. Without the `pop` a person who signed in at `/accounts/login/`
    # and then answered a code at `/accounts/login/?next=/somewhere` would be
    # landed by the second URL, which is the whole of what V-184 refuses.
    stored = str(request.session.pop(NEXT_KEY, "") or "")
    request.session.pop(TYPED_KEY, None)
    if stored:
        state["next"] = stored
    else:
        state.pop("next", None)
    sociallogin.state = state

    log.info("accounts.signin.finished", outcome="landing", subject=person.subject)
    return cast(HttpResponse, complete_social_login(request, sociallogin))


def _remember_next(request: HttpRequest) -> None:
    """Take the deep link the person arrived with, once, at the start.

    allauth's own reader, so "same origin or nothing" is allauth's rule and
    not a second one of ours: `get_next_redirect_url` drops a URL its adapter
    calls unsafe, which is why a foreign `?next=` lands at
    `LOGIN_REDIRECT_URL` instead of following somebody else's host.
    """
    found = str(get_next_redirect_url(request) or "")
    if found:
        request.session[NEXT_KEY] = found
    else:
        request.session.pop(NEXT_KEY, None)


def _typed(request: HttpRequest) -> str:
    """The login name this ceremony is for — from the form, or from the start.

    The code form and the enrolment form carry no address field, and the
    landing's read of the platform's record is by login name, so the value
    taken at `_password` is what those roads land on.
    """
    posted = str(request.POST.get("email", "")).strip()
    return posted or str(request.session.get(TYPED_KEY, "") or "")


def _platform_provider(request: HttpRequest) -> Any:
    """allauth's registered provider for this deployment's platform, or `None`.

    `None` when nothing is registered, which happens for exactly one reason:
    the browser client's `ZITADEL_CLIENT_ID` is empty, and an empty client id
    disables the provider entirely rather than half-configuring it
    (`config/settings/base.py`). Under `ours` that is a deployment whose
    sign-in door cannot complete, and the honest answer is the outage sentence
    and a 503 — never a traceback, and never a session minted around a
    provider nobody configured.
    """
    try:
        return get_socialaccount_adapter(request).get_provider(request, get_platform_provider_id())
    except (ImproperlyConfigured, LookupError, KeyError, ObjectDoesNotExist):
        log.warning("accounts.signin.unavailable", reason="platform_provider_unregistered")
        return None


# --- the page ----------------------------------------------------------------


def _restart(
    request: HttpRequest, *, note: str = "", email: str = "", status: int = 200
) -> HttpResponse:
    """Back to J2-a, with the sentence that says why. **The ceremony is over.**

    Every road that ends without landing comes through here, and it takes the
    door's own two keys down with the ceremony the seam already dropped —
    one exit, so there is no arm that leaves a stale `?next=` behind for the
    next person on a shared browser to be redirected by.

    **The typed name survives**, which is WATCH F8's whole complaint: a
    refusal that empties the address field makes a person retype something
    that was never wrong. The address comes from this POST when it carried
    one and from the start of the ceremony when it did not, so a timeout on
    the code screen still hands back a filled-in form.
    """
    typed = email or str(request.session.get(TYPED_KEY, "") or "")
    request.session.pop(NEXT_KEY, None)
    request.session.pop(TYPED_KEY, None)
    return _page(request, note=note, email=typed, status=status)


def _page(
    request: HttpRequest,
    *,
    frame: str = "sign_in",
    note: str = "",
    email: str = "",
    status: int = 200,
    **supplied: Any,
) -> HttpResponse:
    """One frame, inside the entrance shell, with what the door supplies to it.

    The shell is `account/login.html` and the frame switch is A4's: the door
    hands a NAME and the template includes `account/frames/<name>.html`, so a
    frame this door invents is `TemplateDoesNotExist` naming what it looked
    for rather than a plausible screen. `frame_title` rides with it; the two
    move together because a title that disagreed with the frame is exactly the
    defect A4's verifier found.
    """
    context: dict[str, Any] = {
        "frame": frame,
        "frame_title": FRAME_TITLES[frame],
        "note": note,
        "email": email,
        # The *Forgot your password?* link, built here so it carries the deep
        # link the person arrived with. A bare `?forgot=1` in the template
        # REPLACES the query it is on, which would quietly drop a `?next=`
        # for anybody who detoured through the reset road — the one thing
        # design J5 says must survive it.
        "forgot": _forgot_link(request),
        # **The door answers "does this deployment have a passkey road", and
        # the frame draws nothing at all when it does not** — no button, and
        # no script tag either. An IP address is not a relying-party id and
        # no browser will run a ceremony against one, which is exactly what
        # the shipped `PUBLIC_BASE_URL` is, so this is the common case rather
        # than the exotic one. The BROWSER's half of the answer is the static
        # file's: the button ships `hidden`.
        "passkey_road": frame == "sign_in" and signin.passkey_road_open(),
        **supplied,
    }
    return render(request, "account/login.html", context, status=status)
