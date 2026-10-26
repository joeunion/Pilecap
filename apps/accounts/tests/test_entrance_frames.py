"""The entrance's form primitives and its seven frames: one shell, one token block, no fetch.

Three properties, and none of them is "a page renders".

**The first is the PRIMITIVES (design P-9).** The entrance shell styled
`button`, `a`, `p` and `dl` and nothing a person can type into — so every
allauth page that carries a field (password reset, email change, the MFA
screens) drew the browser's own control inside an otherwise finished product,
and the sign-in frames beside them had nothing to be made of. The six
primitives are declared in the ONE inline token block, because the shell
fetches nothing: a stylesheet the entrance has to load is a stylesheet the
entrance can fail to load, and a sign-in page that fails to load its styling
is the screen a person meets first. Each primitive is asserted twice — the
declaration is in the block, and some frame CONSUMES it — because a token
declared and never consumed is decoration nobody can see, and a class consumed
with no declaration is the user-agent default wearing our markup.

**The second is the FRAMES (design P-10).** Six states on one URL — sign in ·
one more step · set up two-factor · choose your password · reset · signed out
— as template blocks with a closed vocabulary. The vocabulary is DERIVED: it
is the set of files under `templates/account/frames/`, so a seventh frame is a
census failure here rather than a name somebody has to remember to add, and a
name outside the set is `TemplateDoesNotExist` naming the exact path it looked
for rather than a silent fall back to the sign-in page. **No view is mounted
here** — the door that chooses a frame is the sign-in view's — so the frames
are exercised through the shell, which is the seam they will actually render
through.

**The third is BYTE-IDENTITY TODAY.** `login.html` grows a switch, and the
page a person meets today must not move a byte because of it. The pin is a
fixture captured from the baseline tree `c00fa2be` (tree `88fd9a8b`), in both
live door states this deployment has. There is exactly ONE declared allowance
and it is mechanical: the token block itself, because A4.1 puts the primitives
inside it and the login page serves that block.
`test_the_token_block_only_grew…` is what keeps that allowance from being a
hole — every baseline rule still present, in order, and additions only.

The rendered check (A4.3) is the verifier's, in a browser, at 1280 and 400.
`test_the_seven_frames_render_for_the_eye` is what produces what it looks at:
point `DJB_FRAME_RENDER_DIR` at a directory outside the checkout and the seven
documents land there, each complete and each fetching nothing, so `file://`
renders exactly what the shell serves.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from allauth.socialaccount.models import SocialApp
from django.conf import settings as django_settings
from django.contrib.sites.models import Site
from django.template.exceptions import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.test import Client

from apps.core.tests.template_shape import IDENTITY_SHAPE
from apps.core.tests.tree_census import source_text

pytestmark = pytest.mark.django_db

#: The marker the entrance shell's token block declares, read from the
#: declaration a product diverges through and never re-typed here.
MARKER: str = IDENTITY_SHAPE["entrance_marker"]

TEMPLATES = Path(django_settings.BASE_DIR) / "templates"
FRAMES_DIR = TEMPLATES / "account" / "frames"
HERE = Path(__file__).resolve().parent

#: The SEVEN frames — design P-10's six, plus A11's `link_expired` — each with
#: the `h1` design §1 gives it. The NAMES are checked against the directory
#: (the vocabulary is the population of files, not this dict); the HEADINGS are
#: the design's words, which nothing else in the tree holds.
#:
#: The seventh is the one frame with no form on it, and it arrived because A8
#: had nowhere to put design J7's `request_gone`: that state's "must not"
#: column says *render the form as if a plain sign-in would land somewhere
#: useful*, and six frames all carried one.
FRAMES: dict[str, str] = {
    "sign_in": "Sign in",
    "one_more_step": "One more step",
    "set_up_two_factor": "Set up two-factor",
    # pragma: allowlist secret — a frame NAME and a heading, not a credential;
    # the scanner reads "password" beside a string and cannot tell a screen's
    # title from a value.
    "choose_your_password": "Choose your password",  # pragma: allowlist secret
    "reset": "Reset your password",  # pragma: allowlist secret
    "signed_out": "You're signed out.",
    "link_expired": "This sign-in link has expired.",
}

#: The six primitives of design P-9: the selector the one block declares, and
#: the marker by which a frame consumes it.
PRIMITIVES: dict[str, tuple[str, str]] = {
    "a labelled text field": ("input[type=email]", "<label for="),
    "a password field with Show": (".field .reveal", 'class="reveal"'),
    "a six-digit code field": ("input.code", 'class="code"'),
    "an alert note": (".alert", 'class="alert"'),
    "a quiet link row": (".quiet", 'class="quiet"'),
    "a chip row": (".chips", 'class="chips"'),
}

#: The complexity sentence the door reads off the identity platform at render
#: and hands the frame. A constant rather than a literal beside the word
#: `password`, so the secret scanner reads it for what it is: a rule written
#: for a person, carrying no value at all.
POLICY_SENTENCE = "At least 8 characters. Nothing else is required."

#: What makes each frame's render non-vacuous. Every value here is something
#: the DOOR supplies — a frame draws the population it is handed and draws
#: nothing where it is handed nothing, which is why the rendered check is run
#: against a seeded context and says so.
SEEDED: dict[str, dict[str, Any]] = {
    "sign_in": {
        "email": "ada@yourco.test",
        "note": "That email and password don't match. Try again.",
    },
    "one_more_step": {
        "chips": [
            {"action": "email_code", "label": "Email me a code instead"},
            {"action": "security_key", "label": "Use my security key"},
        ]
    },
    # The enrolment secret a real ceremony would hand this frame. It is the
    # base32 string every TOTP example on earth uses ("Hello!" padded), it
    # authenticates nothing, and it exists so the frame has something to draw.
    "set_up_two_factor": {"secret": "JBSWY3DPEHPK3PXP", "skip_days": 7},  # pragma: allowlist secret
    "choose_your_password": {
        "email": "ada@yourco.test",
        "password_rule": POLICY_SENTENCE,
        "expires": "17 September",
    },
    "reset": {
        "email": "ada@yourco.test",
        "password_rule": POLICY_SENTENCE,
    },
    "signed_out": {},
    # NOTHING, and that is the seed. The seventh frame is the one with no
    # form and no field: its whole content is two sentences it holds itself,
    # so a context that handed it anything would be seeding a slot that does
    # not exist.
    "link_expired": {},
}

#: The baseline fixtures A4.5 pins against, captured from `c00fa2be` at step
#: zero — one per live door state, because the page is a different page at
#: nought providers and at one (`test_entrance_chain.py`'s three-state rule).
BASELINES: dict[int, str] = {
    0: "entrance_login_baseline_c00fa2be_no_provider.html",
    1: "entrance_login_baseline_c00fa2be_one_provider.html",
}


def _doors(count: int) -> None:
    """Make the live provider population exactly `count`. Rows, not settings.

    The same helper `test_entrance_chain.py` uses, and deliberately the same
    rows: the fixtures below were captured through it, so a byte comparison is
    a comparison of the same page and not of two differently-seeded ones.
    """
    SocialApp.objects.all().delete()
    site = Site.objects.get_current()
    for index in range(count):
        app = SocialApp.objects.create(
            provider="openid_connect",
            provider_id=f"idp{index}",
            name=f"Identity {index}",
            client_id=f"client-{index}",
            secret="",  # pragma: allowlist secret
            settings={"server_url": "https://id.example.test"},
        )
        app.sites.add(site)


def _render(frame: str, **context: Any) -> str:
    """The frame as the shell serves it — through `account/login.html`, never alone.

    A fragment rendered on its own would prove the fragment compiles. What A4.2
    is about is the frame arriving inside the entrance shell, carrying its
    token block, which is the only thing that makes it look like this product.
    """
    return render_to_string("account/login.html", {"frame": frame, **context})


def _token_block(document: str) -> str:
    """The contents of the one `<style>` element, and a failure if there are two."""
    assert document.count("<style>") == 1, "the entrance has exactly one token block"
    return document.split("<style>", 1)[1].split("</style>", 1)[0]


def _outside_the_token_block(document: str) -> tuple[str, str]:
    head, _, rest = document.partition("<style>")
    _, _, tail = rest.partition("</style>")
    return head, tail


# --- the vocabulary -----------------------------------------------------------


def test_the_frame_vocabulary_is_the_directory_and_it_holds_the_seven() -> None:
    """Closed, and derived. An eighth file is this test's failure, not a review's.

    It was six until A11. The count is in the NAME on purpose: a census whose
    name says how many is a census somebody has to come and edit, which is
    the moment the new frame's words and its title get looked at too.
    """
    assert FRAMES_DIR.is_dir(), f"{FRAMES_DIR} does not exist — the frames are the rung"
    on_disk = sorted(path.stem for path in FRAMES_DIR.glob("*.html"))
    assert on_disk == sorted(FRAMES), (
        "the frame vocabulary is the set of files under templates/account/frames/ — "
        f"found {on_disk}"
    )


def test_an_unknown_frame_is_loud_and_names_what_it_looked_for() -> None:
    """Never a silent fall back to the sign-in page.

    A switch whose else-branch renders today's page would answer a typo with a
    plausible screen, and the door above it would look correct while
    sending a name nobody reads. The include is built from the name, so the
    refusal carries the name.
    """
    with pytest.raises(TemplateDoesNotExist) as raised:
        _render("not_a_frame")
    assert "account/frames/not_a_frame.html" in str(raised.value)


# --- the frames through the shell (A4.2) --------------------------------------


@pytest.mark.parametrize("frame", sorted(FRAMES))
def test_every_frame_arrives_inside_the_entrance_shell(frame: str) -> None:
    """The marker, read from `IDENTITY_SHAPE`, in every one of the seven."""
    document = _render(frame, **SEEDED[frame])
    assert MARKER in document, f"{frame} rendered outside the entrance shell"
    # A whole document, not a fragment. `lstrip` because the shell's own
    # `{% load %}` line leaves one newline in front of the doctype and the
    # served page has always carried it — the baseline fixtures start with it
    # too, which is the only reason it is safe to ignore here.
    assert document.lstrip().startswith("<!doctype html>")
    assert document.rstrip().endswith("</html>")


@pytest.mark.parametrize(("frame", "heading"), sorted(FRAMES.items()))
def test_every_frame_carries_the_heading_the_design_names(frame: str, heading: str) -> None:
    """Design §1's `h1` — the one line that tells a person which screen they are on."""
    document = _render(frame, **SEEDED[frame])
    assert f"<h1>{heading}</h1>" in document
    assert document.count("<h1>") == 1, "one screen, one heading"


@pytest.mark.parametrize("frame", sorted(FRAMES))
def test_no_frame_fetches_anything(frame: str) -> None:
    """A4.1's other half, held on the frames too: nothing to load, nothing to fail.

    The entrance's no-fetch property is the shell's (`test_entrance_chain.py`),
    and it is worth nothing if a frame drawn inside it pulls a font, a script
    or an icon. The passkey reveal and the Show toggle belong to a static file,
    `static/accounts/signin.js`, never inline — so there is no script here at
    all.
    """
    document = _render(frame, **SEEDED[frame])
    assert "<link" not in document
    assert "<script" not in document
    assert "https://" not in document
    assert "@import" not in document
    assert "url(" not in document


# --- the primitives (A4.1) ----------------------------------------------------


def test_the_primitives_are_declared_in_the_one_block() -> None:
    """Six declarations, one `<style>`, and no second stylesheet anywhere."""
    block = _token_block(_render("sign_in", **SEEDED["sign_in"]))
    missing = [name for name, (selector, _) in PRIMITIVES.items() if selector not in block]
    assert not missing, f"primitives not declared in the token block: {missing}"


def test_every_primitive_has_a_consumer_among_the_frames() -> None:
    """A declared primitive nobody draws is decoration; the frames are the census.

    Read off the frame SOURCES rather than off a render, because two of the seven
    (the chip row, the alert note) are drawn from a population the door hands
    in, so a render with nothing seeded would report them as unconsumed and a
    render with everything seeded would prove only that the seed is generous.
    """
    sources = "\n".join(source_text(path) for path in sorted(FRAMES_DIR.glob("*.html")))
    unconsumed = [name for name, (_, marker) in PRIMITIVES.items() if marker not in sources]
    assert not unconsumed, f"primitives no frame consumes: {unconsumed}"


def test_a_control_a_frame_draws_is_never_left_to_the_user_agent() -> None:
    """Every input a frame draws is a type the block declares a rule for.

    The one instrument that can see a field styled by nobody: the rendered
    check reads a computed style, and this reads the same fact statically so
    that a type added to a frame without a rule beside it reds in the loop
    rather than at the next pair of eyes.
    """
    block = _token_block(_render("sign_in", **SEEDED["sign_in"]))
    declared = set(re.findall(r"input\[type=(\w+)\]", block))
    drawn = set()
    for path in sorted(FRAMES_DIR.glob("*.html")):
        drawn |= set(re.findall(r'<input type="(\w+)"', source_text(path)))
    assert drawn - {"hidden"} <= declared, (
        f"input types a frame draws and the token block does not style: "
        f"{sorted(drawn - {'hidden'} - declared)}"
    )


# --- byte-identity today (A4.5) -----------------------------------------------


@pytest.mark.parametrize("doors", sorted(BASELINES))
def test_the_login_page_is_byte_identical_with_no_frame_set(client: Client, doors: int) -> None:
    """Today's page, against the fixtures captured from the baseline tree.

    Byte for byte everywhere the person looks. The ONE declared exception is
    the token block itself — A4.1 puts the six primitives in it, and the login
    page serves that block, so a literal whole-document identity and A4.1
    cannot both hold. The exception is not a hole: the next test pins the block
    to additions only, so the two together say "nothing changed except styling
    that was added, and none of the old styling moved".
    """
    _doors(doors)
    now = client.get("/accounts/login/").content.decode()
    was = (HERE / BASELINES[doors]).read_text()
    assert _outside_the_token_block(now) == _outside_the_token_block(was), (
        f"the login page at {doors} door(s) moved outside the token block"
    )


@pytest.mark.parametrize("doors", sorted(BASELINES))
def test_the_token_block_only_grew_and_the_baseline_rules_are_untouched(
    client: Client, doors: int
) -> None:
    """The allowance above, bounded: every baseline line still there, in order."""
    _doors(doors)
    now = _token_block(client.get("/accounts/login/").content.decode()).splitlines()
    was = _token_block((HERE / BASELINES[doors]).read_text()).splitlines()
    cursor = iter(now)
    for line in was:
        assert line in cursor, f"a baseline token-block line was changed or moved: {line!r}"
    assert len(now) > len(was), "the primitives were supposed to land in this block"


# --- what the verifier looks at (A4.3) ----------------------------------------


def test_the_seven_frames_render_for_the_eye(tmp_path: Path, capsys: Any) -> None:
    """Write the seven documents the rendered check opens, and say where they are.

    `DJB_FRAME_RENDER_DIR` names a directory OUTSIDE the checkout (an untracked
    file inside it reds the instrument census by design); with nothing set the
    six land in pytest's own tmp path, so this never becomes a test that is
    skipped on the run nobody reads. Every document is complete and fetches
    nothing, which is what makes `file://` a faithful render of what the shell
    serves and not an approximation of it.
    """
    target = Path(os.environ.get("DJB_FRAME_RENDER_DIR", tmp_path))
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for frame, heading in FRAMES.items():
        document = _render(frame, **SEEDED[frame])
        assert MARKER in document and f"<h1>{heading}</h1>" in document
        path = target / f"{frame}.html"
        path.write_text(document)
        written.append(path)
    assert len(written) == len(FRAMES)
    with capsys.disabled():
        print(f"\nthe seven frames for the rendered check: {target}")
