"""The world every tags test is measured against: `build_branch_world()` plus three widgets.

The subject is the worked example's `Widget`; `widget_takes_tags` adds `"tags"` and
`widget_takes_no_tags` takes it out, both undone by `monkeypatch`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from apps.core.actor import actor_for
from apps.core.tests.permissions_world import BranchWorld, build_branch_world
from apps.djb_tags.models import ATTACHMENT, Tag
from apps.example.models import Widget
from apps.example.services import create_widget


@dataclass(frozen=True)
class TagWorld(BranchWorld):
    """The branch world, and the subjects the tags tests attach to: two widgets at A, one at B."""

    widget_a: Widget
    other_widget_a: Widget
    widget_b: Widget


@pytest.fixture
def widget_takes_tags(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`Widget` takes tags for this test only — ADDED to whatever it declares.

    Additive, never a replacement: a real `attachments` declaration on the class
    stays in force inside the test, so a test can never hide one.
    """
    _takes_tags(monkeypatch, Widget)
    yield


@pytest.fixture
def widget_takes_no_tags(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`Widget` WITHOUT tags for this test only — every other attachment it declares kept.

    The worked example declares `attachments = ("notes", "tags", "files")`, so a
    test asking what a kind that does not take tags is told takes that one word
    OUT, and only it — subtractive, undone by `monkeypatch`, never a hand `del`.
    """
    kept = tuple(kind for kind in getattr(Widget, "attachments", ()) if kind != ATTACHMENT)
    monkeypatch.setattr(Widget, "attachments", kept, raising=False)
    yield


@pytest.fixture
def tag_takes_tags(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A TENANT-WIDE subject that takes tags, for this test only: `Tag` itself.

    The tree has no tenant-wide noun that declares attachments, and `Tag` is the
    nearest tenant-wide kind the resolver already knows — a row with no branch
    of its own, which is the whole of what the landing law's second case needs.
    """
    _takes_tags(monkeypatch, Tag)
    yield


def _takes_tags(monkeypatch: pytest.MonkeyPatch, model: type) -> None:
    declared = tuple(getattr(model, "attachments", ()) or ())
    if ATTACHMENT not in declared:
        monkeypatch.setattr(model, "attachments", (*declared, ATTACHMENT), raising=False)


@pytest.fixture
def world(recorded_workflow_starts: None) -> TagWorld:
    branch = build_branch_world()
    at_b = actor_for(user=branch.owner.user, tenant=branch.tenant, org=branch.b)
    return TagWorld(
        **vars(branch),
        widget_a=create_widget(tenant=branch.tenant, actor=branch.clerk, name="Bench A"),
        other_widget_a=create_widget(tenant=branch.tenant, actor=branch.clerk, name="Duplicate A"),
        widget_b=create_widget(tenant=branch.tenant, actor=at_b, name="Bench B"),
    )
