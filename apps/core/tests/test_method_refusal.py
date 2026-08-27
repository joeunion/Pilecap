"""A wrong METHOD answers in the API's one envelope.

**The property.** `GET` on a POST-only path — `/api/v1/tokens/` — comes back as
`application/json`, status 405, `{detail, code, remedies}` with
`code="method_not_allowed"`, and it carries ninja's own `Allow` header so the
caller is told which method *is* right. It used to be ninja's
`HttpResponseNotAllowed`: `text/html`, the words "Method not allowed", no
`code`. The census in `apps/accounts/tests/test_refusal_envelope.py` found it
and holds the wire probe; this module holds the parts of the property the census
has no place for.

**Why the seam is a wrap and not a handler.** `PathView._sync_view` *returns*
`_not_allowed()` rather than raising, so no `@api.exception_handler` can ever
see it, and no route runs, so nothing per-route can either. `config/api.py`
wraps the two `PathView` views per mounted instance instead — the second
sanctioned wrap of a ninja internal in that module.

**Three things worth their own test, and one that is not.**

* The **async** half. Nothing in this repository mounts an async route today, so
  the async wrap would sit unexecuted and untested until the first product route
  awaits something — which is exactly how a wrapped pair comes to be half
  right. The parity test below builds a scratch async `Router`, wraps its
  `PathView` with the real function, and asserts the two halves answer **byte
  for byte the same thing**.
* **No operation documents a 405.** A wrong method belongs to the PATH, not to
  any route on it: a 405 row on `POST /tokens/` would be claiming that operation
  can answer 405, which it cannot — it is the operation that was never reached.
  The document must stay silent about it, and rule 41's ratchets must not move.
* **The registry does the rest by derivation.** `introspect` and `/llms.txt`
  list the new code without a line of their own, because both read
  `core.exceptions.REFUSALS`. That is the test that would fail if somebody
  "helpfully" special-cased the 405 somewhere instead of registering it.

What is deliberately not tested here is the import-time tripwire: it fires only
when a future ninja renames `_sync_view`/`_async_view`, and the only way to
reach it is to hand `_speak_the_method_refusal` an object that is not a
`PathView`. That is asserted below as the cheap thing it is — a plain object —
rather than by monkeypatching ninja.
"""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.http import HttpRequest
from django.test import Client, RequestFactory
from django.urls import reverse
from ninja import Router

from apps.core.exceptions import REFUSALS
from config.api import _speak_the_method_refusal, api

TOKENS = "/api/v1/tokens/"
WIDGETS = "/api/v1/widgets/"

ENVELOPE_KEYS = {"detail", "code", "errors", "remedies"}


def _body(response: Any) -> dict[str, Any]:
    """The parsed body, having first insisted the refusal really is JSON."""
    content_type = response.headers.get("Content-Type", "")
    assert content_type.startswith("application/json"), (
        f"a wrong method answered {content_type!r}: {response.content[:200]!r}"
    )
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


# --- the wire -----------------------------------------------------------------


@pytest.mark.django_db
def test_a_wrong_method_answers_json_with_a_code_and_an_allow_header(client: Client) -> None:
    """`GET /api/v1/tokens/` — the census's own find, driven through the mount.

    No credential is sent on purpose: the method is decided by the router before
    any authenticator runs, so a 405 is one of the very few answers this API
    gives an anonymous caller. That it is a *complete* envelope for that caller
    is the point.
    """
    response = client.get(TOKENS)

    assert response.status_code == 405
    assert response["Allow"] == "POST"
    body = _body(response)
    assert set(body) <= ENVELOPE_KEYS
    assert body["code"] == "method_not_allowed"
    assert body["detail"] == "That path answers POST, not GET."
    assert body["remedies"], "a dead end with a status code on it"


@pytest.mark.django_db
def test_the_sentence_lists_every_method_the_path_does_answer(client: Client) -> None:
    """`/api/v1/widgets/` answers GET and POST; a DELETE at it is told both.

    The methods come from ninja's own `Allow` set and nowhere else — this is the
    test that would fail if `config/api.py` ever grew a table of what a path
    answers, which is the copy of the routing that must not exist.
    """
    response = client.delete(WIDGETS)

    assert response.status_code == 405
    assert set(response["Allow"].replace(" ", "").split(",")) == {"GET", "POST"}
    assert _body(response)["detail"] == "That path answers GET or POST, not DELETE."


# --- the async half, proven against a scratch router --------------------------


def _scratch_async_path_view() -> Any:
    """One POST-only path whose view is `async def`, and nothing else.

    A scratch `Router` rather than a route added to a real app: mounting an
    async route on `config.api.api` to test this would put a fake operation in
    the live document, in `introspect`, and in front of rule 41's census. The
    `PathView` is the whole subject here, and a bare router produces the same
    one the mount would.
    """
    router = Router()

    @router.post("/scratch/")
    async def scratch(request: HttpRequest) -> dict[str, str]:  # pragma: no cover - never run
        """A route that exists only to be missed by a GET."""
        return {"ok": "never reached"}

    path_view = router.path_operations["/scratch/"]
    assert path_view.is_async, "the scratch route is not async, so it proves nothing"
    return path_view


@pytest.mark.asyncio
async def test_the_async_half_answers_byte_for_byte_what_the_sync_half_answers() -> None:
    """Parity, stated as equality rather than as two similar assertions.

    Both halves of the wrap are applied by one function and both call one
    translator, so the interesting claim is not "the async one also returns 405"
    — it is that a caller cannot tell which half answered. Anything that drifted
    (a differently-sorted sentence, a re-rendered `Allow`, a body composed at the
    second site) shows up here as an inequality.
    """
    path_view = _scratch_async_path_view()
    _speak_the_method_refusal(path_view)
    request = RequestFactory().get("/scratch/")

    from_sync = path_view._sync_view(request)
    from_async = await path_view._async_view(request)

    assert from_async.status_code == from_sync.status_code == 405
    assert from_async["Allow"] == from_sync["Allow"] == "POST"
    assert from_async["Content-Type"] == from_sync["Content-Type"]
    assert from_async.content == from_sync.content
    body = json.loads(from_async.content)
    assert set(body) <= ENVELOPE_KEYS
    assert body["code"] == "method_not_allowed"
    assert body["detail"] == "That path answers POST, not GET."


def test_an_answer_that_is_not_a_405_is_handed_back_untouched() -> None:
    """The wrap translates one shape and passes everything else through.

    Asserted with identity — `is` — because "did not touch it" is the property.
    A wrap that rebuilt every response on its way out would be middleware
    wearing a different name — the approach rejected in favor of this wrap.
    """
    path_view = _scratch_async_path_view()
    _speak_the_method_refusal(path_view)
    sentinel = object()
    path_view._find_operation = lambda request: None
    path_view._not_allowed = lambda: sentinel

    assert path_view._sync_view(RequestFactory().get("/scratch/")) is sentinel


def test_a_renamed_ninja_internal_is_a_runtime_error_naming_the_mechanism() -> None:
    """The tripwire. A quiet no-op here is markup on the wire nobody notices.

    Same shape and same reasoning as `_guard_the_ceiling`'s: the failure mode of
    a wrapper attached to a private attribute is that the attribute moves and the
    wrapper silently stops running, so the missing attribute fails the import
    loudly instead.
    """

    class NotAPathView:
        pass

    with pytest.raises(RuntimeError) as raised:
        _speak_the_method_refusal(NotAPathView())

    assert "method-refusal" in str(raised.value)
    assert "_sync_view" in str(raised.value)


# --- the document stays silent, and the registry does the talking -------------


def test_no_operation_in_the_document_claims_it_can_answer_405() -> None:
    """The 405 belongs to the path, so no route enumerates it (rule 41 unmoved).

    Two assertions, because there are two ways a 405 row could appear: a
    `responses` entry, and a code in `x-refusal-codes` that `CODE_STATUS` would
    then turn into one.
    """
    schema = api.get_openapi_schema()

    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses", {})
            assert not {405, "405"} & set(responses), f"{method.upper()} {path} documents a 405"
            for response in responses.values():
                codes = response.get("x-refusal-codes", []) if isinstance(response, dict) else []
                assert "method_not_allowed" not in codes, f"{method.upper()} {path}"


@pytest.mark.django_db
def test_introspect_and_llms_txt_carry_the_new_code_by_derivation(client: Client) -> None:
    """Neither file was edited directly, and both say the new thing.

    `introspect` reads `core.exceptions.REFUSALS` and `/llms.txt` prints one line
    per registered code off the same mapping, which is the whole reason the
    refusal is *registered* rather than special-cased inside the wrap.
    """
    out = StringIO()
    call_command("introspect", stdout=out)
    reported = {row["code"] for row in json.loads(out.getvalue())["refusals"]}
    assert "method_not_allowed" in reported

    fact = REFUSALS["method_not_allowed"].fact
    llms = client.get(reverse("llms-txt")).content.decode()
    assert f"method_not_allowed: {fact}" in llms


def test_the_refusal_component_enumerates_it_like_every_other_code() -> None:
    """`openapi.json`'s one refusal schema lists every registered code.

    Enumerated off `REFUSALS`, so a generated client can switch on the new code
    without anybody adding it to a second list.
    """
    schema = api.get_openapi_schema()
    refusal = schema["components"]["schemas"]["Refusal"]

    assert "method_not_allowed" in refusal["properties"]["code"]["enum"]
