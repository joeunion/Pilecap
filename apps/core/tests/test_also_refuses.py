"""`@also_refuses`: a route ADDS a code to the set it publishes, and restates nothing.

The composition runs through the mount's own documentation pass
(`config.api._document_operation`) over a throwaway router, so what is proved
is the published `x-refusal-codes` a generated client reads — not a helper.
"""

from __future__ import annotations

from typing import Any

from ninja import NinjaAPI, Router

from apps.core.api.docs import (
    added_refusals,
    also_refuses,
    declared_refusals,
    derived_refusals,
    refuses,
    with_added,
)
from config import api as mount


def _published(router: Router) -> dict[str, set[str]]:
    """url_name -> every code the documentation pass published for that route."""
    api = NinjaAPI(urls_namespace="zzz_also_refuses")
    api.add_router("/zzz/", router)
    out: dict[str, set[str]] = {}
    for bound in api._get_bound_routers():
        for path, path_view in bound.path_operations.items():
            for operation in path_view.operations:
                mount._document_operation(path, operation)
                codes: set[str] = set()
                for body in (operation.openapi_extra or {}).get("responses", {}).values():
                    if isinstance(body, dict):
                        codes |= set(body.get("x-refusal-codes") or ())
                out[str(operation.url_name)] = codes
    return out


def _routes() -> Router:
    router = Router()

    @router.post("/{row_id}/archive/", url_name="zzz-derived")
    def derived(request: Any, row_id: str) -> None:
        """Archive a row

        The derivation alone.
        """

    @router.post("/{row_id}/archive-too/", url_name="zzz-added")
    @also_refuses("archive_blocked")
    def added(request: Any, row_id: str) -> None:
        """Archive a row

        The derivation, plus the one code this route can also answer.
        """

    @router.post("/{row_id}/archive-narrow/", url_name="zzz-narrowed")
    @refuses("not_found")
    def narrowed(request: Any, row_id: str) -> None:
        """Archive a row

        A route that narrows, as the eight shipped narrowers do.
        """

    @router.post("/{row_id}/archive-both/", url_name="zzz-both")
    @refuses("not_found")
    @also_refuses("archive_blocked")
    def both(request: Any, row_id: str) -> None:
        """Archive a row

        Narrowed, and one code added to the narrowed set.
        """

    return router


def test_also_refuses_publishes_the_derived_set_plus_its_code() -> None:
    published = _published(_routes())
    assert "archive_blocked" in published["zzz-added"]
    assert published["zzz-added"] == published["zzz-derived"] | {"archive_blocked"}
    assert "archive_blocked" not in published["zzz-derived"]


def test_refuses_still_narrows_and_also_refuses_adds_to_the_narrowed_set() -> None:
    published = _published(_routes())
    assert "conflict" in published["zzz-derived"]
    assert "conflict" not in published["zzz-narrowed"]
    assert published["zzz-both"] == published["zzz-narrowed"] | {"archive_blocked"}


def test_the_additions_are_read_off_the_view_and_filtered_by_the_registry() -> None:
    @also_refuses("archive_blocked", "zzz_never_registered")
    def view() -> None: ...

    assert added_refusals(view) == ("archive_blocked", "zzz_never_registered")
    assert declared_refusals(view) is None
    base = derived_refusals(
        methods=["POST"],
        has_path_params=True,
        has_body=False,
        authenticated=True,
        idempotent_methods=[],
    )
    composed = with_added(base, view)
    assert composed[: len(base)] == base
    assert composed[-1] == "archive_blocked"
    assert "zzz_never_registered" not in composed
