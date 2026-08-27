"""The docs page renders Scalar, from bytes this repository is carrying.

Three properties, and none of them is "a page renders".

**It is OFFLINE.** The laptop stack works with the network unplugged and so do
air-gapped deployments, so the docs page may not reach a CDN for the renderer,
a webfont, or a request proxy. That is testable as a flat statement about the
response body — *no external origin appears in it at all* — which is why
`test_the_page_names_no_external_origin` matches on `http`, `https` and
protocol-relative `//host` rather than on a list of hosts somebody would have
to remember to extend.

**THE DOCUMENT DID NOT MOVE.** `openapi.json` is the contract (ADR api-1); the
renderer is a reader of it. `test_the_document_is_renderer_agnostic` mounts
ninja's own Swagger back for the duration of one request and demands the two
responses be byte-equal — the property "swapping the renderer changed nothing
about the contract", asserted rather than assumed.

**THE VENDORED BYTES ARE THE PINNED BYTES.** `vendor/scalar/MANIFEST.toml` is
the whole supply-chain posture for an asset no Python audit reads (house rule
23 covers pip, licences and the secret scan; none of the three sees a
JavaScript bundle). A checksum in a file that nothing checks is decoration, so
the gate checks it here, and a bundle swapped without the manifest being
updated is a red test rather than a quiet diff.

The same three properties are asserted again at the bottom against `/llms.txt`,
the third rendering of the same document — derived at request time, never a file
in the tree, and plain text so that the reader it is for does not have to strip
markup out of it first.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
from html import unescape
from pathlib import Path
from typing import Any, cast

import pytest
from django.conf import settings
from django.http import StreamingHttpResponse
from django.templatetags.static import static
from django.test import Client
from django.urls import reverse
from ninja.openapi.docs import Swagger

from apps.core.api import docs
from apps.core.exceptions import REFUSALS
from apps.core.mcp import MCP_PATH
from config.api import api

pytestmark = pytest.mark.django_db

#: Any absolute or protocol-relative origin. The offline criterion is that this
#: finds nothing in the docs page — stated as a shape, not as a deny-list of
#: hosts, because a deny-list is a list somebody forgets to extend the day the
#: bundle's defaults change.
EXTERNAL_ORIGIN = re.compile(r"(?:https?:)?//[A-Za-z0-9.-]+")

#: Where the vendored artefacts and their posture live.
VENDOR_DIR = Path(settings.BASE_DIR) / "vendor" / "scalar"


@pytest.fixture
def page(client: Client) -> Any:
    return client.get(reverse("api:openapi-view"))


@pytest.fixture
def manifest() -> dict[str, Any]:
    with (VENDOR_DIR / "MANIFEST.toml").open("rb") as handle:
        loaded: dict[str, Any] = tomllib.load(handle)
    return loaded


@pytest.fixture
def artifact(manifest: dict[str, Any]) -> dict[str, Any]:
    """The one artefact pinned here, found by name and not by position."""
    for entry in manifest["artifact"]:
        if entry["name"] == "scalar-api-reference":
            found: dict[str, Any] = entry
            return found
    raise AssertionError("MANIFEST.toml no longer pins scalar-api-reference")


def _configuration(body: str) -> dict[str, Any]:
    """What the page tells the bundle, parsed back out of the page."""
    match = re.search(r'id="api-reference" data-configuration="([^"]*)"', body)
    assert match, "the page no longer carries a Scalar configuration"
    parsed: dict[str, Any] = json.loads(unescape(match.group(1)))
    return parsed


# --- it answers, and it is Scalar ---------------------------------------------


def test_the_docs_url_answers_html(page: Any) -> None:
    """200 and HTML, to an anonymous client: the contract is readable by anyone."""
    assert page.status_code == 200
    assert page["Content-Type"].startswith("text/html")


def test_the_mounted_renderer_is_ours(page: Any) -> None:
    """The API carries the instance `apps.core.api.docs` exports, not a lookalike.

    Asserted against the object rather than against the rendered markup so the
    failure names the cause — somebody passed a different `docs=` — instead of
    a diff of HTML.
    """
    assert api.docs is docs.SCALAR


def test_the_page_loads_the_local_bundle(page: Any) -> None:
    """The one script the page fetches is the vendored file, at its static URL.

    `static()` and not a typed path: under production's manifest storage the
    URL carries a content hash, and a test pinning `/static/vendor/...`
    literally would pass on a laptop and lie about production.
    """
    body = page.content.decode()
    assert f'<script src="{static(docs.SCALAR_BUNDLE)}"></script>' in body
    assert body.count("<script") == 2  # the configuration, and the bundle


def test_the_page_points_at_this_mount_s_document(page: Any) -> None:
    """The document URL is reversed, so moving the mount moves the page with it."""
    assert _configuration(page.content.decode())["url"] == reverse("api:openapi-json")


# --- the offline criterion ----------------------------------------------------


def test_the_page_names_no_external_origin(page: Any) -> None:
    """Nothing in the page reaches outside this deployment. The whole criterion."""
    assert EXTERNAL_ORIGIN.findall(page.content.decode()) == []


def test_the_bundles_own_phone_home_defaults_are_off(page: Any) -> None:
    """Left alone the bundle fetches a webfont and proxies "try it" through Scalar.

    Neither is visible in the page source — they happen at runtime, from inside
    the bundle — so the offline regex above cannot see them and this test states
    them directly.
    """
    configuration = _configuration(page.content.decode())
    assert configuration["withDefaultFonts"] is False
    assert configuration["proxyUrl"] == ""
    assert configuration["hideClientButton"] is True


def test_the_page_offers_neither_an_assistant_nor_a_second_machine_door(
    page: Any,
) -> None:
    """**The platform offers no agent; `/mcp` is the door for the user's own**
    (design-agreements.md).

    Two of the bundle's sidebar features are off, and the docs page is a surface
    like any other. "Ask AI" is an assistant this platform does not ship — and,
    secondarily, its flow POSTs this deployment's whole OpenAPI document to
    Scalar's service to embed it. "Generate MCP"
    manufactures a second machine door out of the document, with none of the
    guarantees the real one at `/mcp` carries — same services, tenancy
    revalidated, refusals byte-identical, audited, held to the HTTP door by
    house rule 17 — and a disagreement between two doors is a finding here.

    Asserted on the configuration the page actually paints, because a default
    that happens to be off today is not a posture: the bundle decides both by
    inspecting `window.location.href` unless it is told.
    """
    configuration = _configuration(page.content.decode())
    assert configuration["agent"] == {"disabled": True}
    assert configuration["mcp"] == {"disabled": True}


def test_the_vendored_bundle_is_served_and_is_the_committed_file(
    client: Client, artifact: dict[str, Any]
) -> None:
    """The static URL the page names really answers, with the pinned bytes.

    The page referencing a local path proves nothing on its own: a path that
    404s is a blank docs page with no error anyone sees. This follows it.

    WhiteNoise answers a static file by streaming it, so the body is drained
    with `getvalue()` rather than read from `.content`, which on a streaming
    response raises rather than returning it. The cast is what the test
    client's own return annotation costs: it promises the WSGI response class,
    and this route legitimately answers with the other one.
    """
    response = client.get(static(docs.SCALAR_BUNDLE))
    assert response.status_code == 200
    assert response.streaming
    body = cast(StreamingHttpResponse, response).getvalue()
    assert hashlib.sha256(body).hexdigest() == artifact["sha256"]
    assert len(body) == artifact["bytes"]


# --- Swagger is gone, not hidden ----------------------------------------------


def test_swagger_no_longer_answers_anywhere(page: Any) -> None:
    """Ninja mounts ONE docs route; it renders Scalar, so there is no second door.

    Ninja's Swagger assets are still installed under `/static/ninja/`, inert:
    nothing renders the template that loads them. That is the declared residue —
    an unreferenced file, not a page.
    """
    body = page.content.decode().lower()
    assert "swagger" not in body
    assert not isinstance(api.docs, Swagger)
    docs_routes = [
        pattern for pattern in api.urls[0] if getattr(pattern, "name", None) == "openapi-view"
    ]
    assert len(docs_routes) == 1


# --- the document did not move ------------------------------------------------


def test_the_document_is_renderer_agnostic(client: Client) -> None:
    """`openapi.json` is byte-identical with Swagger mounted and with Scalar mounted.

    The renderer is swapped for the duration of one request and put back in a
    `finally`, because `api` is module state every other test in the process
    shares.
    """
    url = reverse("api:openapi-json")
    with_scalar = client.get(url)
    assert with_scalar.status_code == 200
    assert with_scalar["Content-Type"].startswith("application/json")

    previous = api.docs
    try:
        api.docs = Swagger()
        with_swagger = client.get(url)
    finally:
        api.docs = previous

    assert with_swagger.content == with_scalar.content


# --- the index still gets there -----------------------------------------------


def test_the_index_still_links_to_the_docs_and_the_link_works(client: Client) -> None:
    """`/` reverses the docs route; following it is a 200, not a 404."""
    index = client.get("/")
    assert index.status_code == 200
    href = reverse("api:openapi-view")
    assert f'href="{href}"' in index.content.decode()
    assert client.get(href).status_code == 200


# --- the manifest is the posture, so the gate reads it ------------------------


def test_the_manifest_pins_the_bytes_that_are_committed(artifact: dict[str, Any]) -> None:
    """The committed file hashes to what the manifest says, or this is red.

    This is the whole enforcement for a vendored browser asset: pip-audit,
    pip-licenses and detect-secrets (house rule 23) all read Python or the
    tree's own text, and none of them would notice these bytes changing under
    the same filename.
    """
    committed = (VENDOR_DIR / artifact["file"]).read_bytes()
    assert hashlib.sha256(committed).hexdigest() == artifact["sha256"]
    assert len(committed) == artifact["bytes"]


def test_the_manifest_states_a_posture_and_its_limits(
    manifest: dict[str, Any], artifact: dict[str, Any]
) -> None:
    """Version, source, licence — and what a checksum does NOT prove."""
    assert artifact["version"] in artifact["file"]
    assert artifact["version"] in artifact["source_url"]
    assert artifact["license"] == "MIT"
    assert (VENDOR_DIR / artifact["license_file"]).is_file()
    assert manifest["not_covered"]["statement"].strip()


def test_the_bundle_carries_no_dangling_source_map(artifact: dict[str, Any]) -> None:
    """The one transform, held in place by a test rather than by memory.

    Upstream's file ends with `//# sourceMappingURL=standalone.js.map` and the
    map is 14.7 MB, so it is not vendored. Django's ManifestStaticFilesStorage
    — this project's production staticfiles backend — rewrites sourceMappingURL
    targets during `collectstatic` and RAISES on one it cannot resolve, so
    letting that line back in breaks the production image build and nothing
    earlier. The gate is here because the gate does not run `collectstatic`.
    """
    assert "sourceMappingURL" not in (VENDOR_DIR / artifact["file"]).read_text()


# --- /llms.txt: the same contract, for the other kind of reader ---------------
#
# The properties are the same three, pointed at a different rendering. It is
# DERIVED (a sentinel route's own summary appears in it, and the sentinel is
# found in the live registry rather than typed here, so the test cannot pass by
# agreeing with a stale copy of itself). It is TEXT (no markup, `text/plain`).
# And it is NOT A FILE — nothing in the tree is served, so it cannot go stale.


@pytest.fixture
def llms(client: Client) -> Any:
    return client.get(reverse("llms-txt"))


@pytest.fixture
def sentinel() -> tuple[str, str, str]:
    """One real operation, taken from the live document: (method, path, summary).

    Chosen by scanning rather than typed, and the scan demands a summary, so a
    repository whose routes are all renamed still yields a sentinel and the
    test still means what it says.
    """
    schema = api.get_openapi_schema()
    for path in sorted(schema["paths"]):
        for method, operation in sorted(schema["paths"][path].items()):
            summary = str(operation.get("summary", "")).strip()
            if summary:
                return method, path, summary
    raise AssertionError("no operation in the live document carries a summary")


def test_llms_txt_answers_as_plain_text(llms: Any) -> None:
    """200 and `text/plain`. A docs surface served as HTML is a docs surface an
    agent has to strip tags out of before it can read it."""
    assert llms.status_code == 200
    assert llms["Content-Type"].startswith("text/plain")


def test_llms_txt_carries_the_live_registrys_own_prose(
    llms: Any, sentinel: tuple[str, str, str]
) -> None:
    """A real operation's method, path and summary are all in the text.

    This is the derivation asserted: the sentinel is read out of
    `get_openapi_schema()` at test time, so the only way to pass is to have been
    generated from the same registry. A checked-in file would fail the first
    time a route was renamed — which is exactly the failure it is here to make
    impossible.
    """
    method, path, summary = sentinel
    body = llms.content.decode()
    assert f"### {method.upper()} {path}" in body
    assert summary in body


def test_llms_txt_prints_the_title_and_then_the_sentence(llms: Any) -> None:
    """The title/description split reaches the text rendering too.

    Before 2026-08-24 `summary` was the first line of `description`, so this
    block printed the description alone and the summary only when there was no
    description. They no longer overlap, so printing one would drop half the
    answer — and the title has to come FIRST, because "which call" is the
    question an agent is answering here.
    """
    schema = api.get_openapi_schema()
    operation = schema["paths"]["/api/v1/tokens/"]["post"]
    block = llms.content.decode().split("### POST /api/v1/tokens/\n", 1)[1]
    block = block.split("### ", 1)[0]
    lines = [line for line in block.splitlines() if line.strip()]
    assert lines[0] == operation["summary"]
    assert operation["description"].splitlines()[0] in block
    assert operation["summary"] not in operation["description"]


def test_llms_txt_counts_the_credential_free_routes_rather_than_claiming_one(
    llms: Any,
) -> None:
    """Two different routes each said they were "the only" one.

    Both were telling the truth as their author remembered it. A number derived
    from the document cannot be wrong in two files at once.
    """
    schema = api.get_openapi_schema()
    root = schema.get("security")
    expected = sum(
        1
        for path in schema["paths"].values()
        for operation in path.values()
        if not operation.get("security", root)
    )
    assert expected >= 2, "the fixture for this test is a document with open routes"
    assert f"{expected} of them require no credential at all" in llms.content.decode()


def test_llms_txt_nests_the_overviews_guides_under_its_own_heading(llms: Any) -> None:
    """The overview owns `##`; embedded here it is a section inside one.

    A `##` nested under a `##` would tell an agent that "Errors" is a sibling of
    "Operations" rather than a part of the overview.
    """
    body = llms.content.decode()
    overview = body.split("## Overview\n", 1)[1].split("## Authentication", 1)[0]
    assert "\n### Quickstart" in overview
    assert "\n## Quickstart" not in overview


def test_llms_txt_contains_no_markup(llms: Any) -> None:
    """No HTML: no closing tag, no doctype, no script.

    Matched on CLOSING tags rather than on `<`, because the contract's own prose
    is full of placeholder syntax — `Authorization: Bearer <token>`,
    `X-Tenant: <slug>` — which a naive `<[a-z]` test would call markup and which
    an agent reading this needs to see exactly as written.
    """
    body = llms.content.decode()
    assert re.search(r"</[A-Za-z][^>]*>", body) is None
    assert "<!DOCTYPE" not in body.upper()
    assert "<script" not in body.lower()


def test_llms_txt_points_at_the_other_doors_by_reversing_them(llms: Any) -> None:
    """The document, the page and the machine door — every URL reversed, none typed."""
    body = llms.content.decode()
    assert reverse("api:openapi-json") in body
    assert reverse("api:openapi-view") in body
    assert MCP_PATH in body


def test_llms_txt_states_the_refusal_grammar_and_every_code(llms: Any) -> None:
    """The shape a caller branches on, and the whole registry — not a subset."""
    body = llms.content.decode()
    assert "code" in body
    for code, refusal in REFUSALS.items():
        assert f"{code}: {refusal.fact}" in body


def test_llms_txt_tells_an_open_route_from_a_closed_one(llms: Any) -> None:
    """Auth is stated per operation, and the two answers are really different.

    An agent that reads "no credential" on a route that wants one gets a 401 it
    has no reason to expect, so this asserts the distinction exists in the text
    rather than that the words appear somewhere in it.
    """
    schema = api.get_openapi_schema()
    root = schema.get("security")
    open_ops = [
        (method, path)
        for path in schema["paths"]
        for method, operation in schema["paths"][path].items()
        if not operation.get("security", root)
    ]
    assert open_ops, "the document declares no unauthenticated operation to check against"

    body = llms.content.decode()
    assert "auth: none" in body
    assert "auth: required" in body
    for method, path in open_ops:
        block = body.split(f"### {method.upper()} {path}\n", 1)[1]
        assert block.split("### ", 1)[0].count("auth: none") == 1


def test_llms_txt_is_not_a_file_in_the_tree(llms: Any) -> None:
    """Nothing named llms.txt is committed: the response is built, every time.

    A checked-in copy is a second contract, and the second contract is the one
    that is wrong. The response changing when the document changes is the
    property; this is the cheap half of it that a reviewer can see at a glance.
    """
    assert not (Path(settings.BASE_DIR) / "llms.txt").exists()
    assert llms.content.decode() == docs.llms_text(api)


# --- the tag surface: what a BYO-agent user can learn from the map alone -------
#
# MEASURED: every tag in the document
# was moved, the reference page changed, and `/llms.txt` came back BYTE
# IDENTICAL. The sections were invisible on the surface an agent actually reads
# — so an agent could not learn that this API has parts, and therefore could not
# learn what the scope families are named after, which is the one thing it needs
# in order to tell a person which token to mint.
#
# The census below is derived from the document on both sides: the set of tag
# sections in the text and the set of tags in the document, compared. Nothing
# here lists a tag, so a tag added, renamed or moved fails this BY NAME.


def tag_sections(body: str) -> dict[str, str]:
    """Every `## ` section of `/llms.txt` that declares a wire tag, by that tag.

    Read off the `tag:` line rather than off the heading, because the heading is
    the DISPLAY name — renamable by design — and a census that matched on it
    would break the day somebody wrote "Accounts & tokens" over `tokens`.
    """
    found: dict[str, str] = {}
    for chunk in body.split("\n## ")[1:]:
        for line in chunk.splitlines():
            if line.startswith(docs.TAG_LINE):
                found[line[len(docs.TAG_LINE) :].strip()] = chunk
                break
    return found


def test_llms_txt_has_one_section_per_document_tag(llms: Any) -> None:
    """The census, both ways: no tag without a section, no section without a tag."""
    schema = api.get_openapi_schema()
    declared = {str(tag["name"]) for tag in schema["tags"]}
    assert declared, "the document declares no tags — this test would pass vacuously"

    sections = tag_sections(llms.content.decode())
    assert set(sections) == declared, (
        f"tags with no section: {sorted(declared - set(sections))}; "
        f"sections with no tag: {sorted(set(sections) - declared)}"
    )


def test_each_tag_section_carries_its_display_name_description_and_scopes(
    llms: Any,
) -> None:
    """The three facts a reader needs before the operations, all derived.

    The scopes are re-derived here through the same function the door enforces
    with, so a section could not print a ceiling the door would not recognise.
    """
    schema = api.get_openapi_schema()
    body = llms.content.decode()
    sections = tag_sections(body)

    for tag in schema["tags"]:
        name = str(tag["name"])
        section = sections[name]
        display = str(tag["x-displayName"])
        assert body.count(f"\n## {display}\n") == 1, f"{name}: display name is not the heading"
        assert str(tag["description"]).strip() in section, f"{name}: declared description missing"

        read = docs.derived_scope(tags=[name], methods=["GET"])
        write = docs.derived_scope(tags=[name], methods=["POST"])
        assert read and write, f"{name}: no scope could be derived for a whole section"
        assert f"{docs.SCOPES_LINE}{read}, {write}" in section, f"{name}: scopes line missing"


def test_every_operation_is_printed_under_its_own_tag(llms: Any) -> None:
    """No operation is orphaned, and none is filed under somebody else's section.

    The failure this closes is the quiet one: a grouping pass that drops an
    operation leaves a text that still reads complete.
    """
    schema = api.get_openapi_schema()
    body = llms.content.decode()
    sections = tag_sections(body)

    counted = 0
    for path in schema["paths"]:
        for method, operation in schema["paths"][path].items():
            if not isinstance(operation, dict):
                continue
            heading = f"### {method.upper()} {path}\n"
            printed = body.count(heading)
            assert printed == 1, f"{heading.strip()} appears {printed} times"
            tags = operation.get("tags") or []
            assert len(tags) == 1, f"{heading.strip()} carries {tags}"
            assert heading in sections[str(tags[0])], (
                f"{heading.strip()} is not under its own section {tags[0]!r}"
            )
            counted += 1
    assert counted >= 30, f"only {counted} operations checked — the document came apart"
    assert docs.UNGROUPED_HEADING not in body, "an operation carries no tag at all"


def test_operations_are_sorted_within_their_section(llms: Any) -> None:
    """Path, then method, inside each section — so a diff between two
    deployments is a real difference and not an insertion-order shuffle."""
    schema = api.get_openapi_schema()
    body = llms.content.decode()

    for tag, section in tag_sections(body).items():
        printed = re.findall(r"^### ([A-Z]+) (\S+)$", section, re.MULTILINE)
        expected = sorted(
            (
                (method.upper(), path)
                for path in schema["paths"]
                for method, operation in schema["paths"][path].items()
                if isinstance(operation, dict) and (operation.get("tags") or [None])[0] == tag
            ),
            key=lambda pair: (pair[1], docs.METHOD_ORDER.index(pair[0].lower())),
        )
        assert printed == expected, tag


def test_moving_a_tag_changes_llms_txt(llms: Any) -> None:
    """The tag-rename repro, closed: the surface that was byte-identical now moves.

    The document is re-rendered with one operation's tag rewritten — nothing on
    disk is touched — and the text has to differ. Before this fix it did not:
    that is the whole finding, and this is the assertion that keeps it shut.
    """
    schema = json.loads(json.dumps(api.get_openapi_schema()))
    before = docs.llms_text(api)

    class Rendered:
        """A stand-in mount that hands back a document somebody moved a tag in."""

        urls_namespace = api.urls_namespace

        def get_openapi_schema(self) -> Any:
            return schema

    moved = "a-different-section"
    for path in sorted(schema["paths"]):
        for operation in schema["paths"][path].values():
            if isinstance(operation, dict) and operation.get("tags"):
                operation["tags"] = [moved]
                break
        else:
            continue
        break

    after = docs.llms_text(cast(Any, Rendered()))
    assert after != before, (
        "moving a tag left /llms.txt byte-identical — the tag-surface fix regressed"
    )
    assert f"{docs.TAG_LINE}{moved}" in after


# --- the arrow points one way -------------------------------------------------
#
# THE CYCLE THAT ONLY A MERGE COULD CREATE. `apps.core.mcp` imports
# `contract_of` from `apps.core.api.docs`, so that a tool and its REST twin
# cannot describe one capability differently (house rule 17, one surface
# earlier). `/llms.txt` wanted the machine door's path from the other side. The
# two halves landed in different rungs, each green on its own branch, and met
# at the merge — where `manage.py check` died with an ImportError naming a
# symbol that plainly exists, because Python hands the second importer a
# PARTIALLY INITIALIZED module rather than refusing.
#
# The invariant is a direction and not a timing, so it is asserted as one: the
# low module does not name the high one at import. An AST reading of the source
# says that in a way a passing import cannot fake — this test process has both
# modules loaded already, so "it imported fine" proves nothing here.


def test_docs_does_not_import_mcp_at_module_scope() -> None:
    """`apps.core.api.docs` names `apps.core.mcp` inside a function or not at all."""
    tree = ast.parse(Path(docs.__file__).read_text())
    offending = [
        node.lineno
        for node in tree.body  # module scope ONLY — a nested import is the fix
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("apps.core.mcp")
    ]
    assert offending == [], (
        f"apps/core/api/docs.py imports apps.core.mcp at module scope (line {offending}); "
        "mcp.py imports contract_of from here, so that closes a cycle the merge cannot survive"
    )


def test_the_lazy_read_returns_the_real_constant() -> None:
    """A lazy read is only safe while it reads the same thing the eager one did.

    Without this the guard above could be satisfied by a hard-coded "/mcp" —
    which is the failure it is meant to prevent, spelled differently.
    """
    assert docs._mcp_path() == MCP_PATH
