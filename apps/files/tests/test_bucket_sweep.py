"""A checkout's bucket is reaped with its database, and only a derived name is ever reaped."""

from __future__ import annotations

import io
import uuid
import warnings
from typing import TYPE_CHECKING

import pytest
from django.conf import settings as django_settings
from django.core.management import call_command

from apps.conftest import organ
from apps.files import storage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Any


def _exists(name: str) -> bool:
    return name in storage.list_derived_buckets()


@pytest.fixture
@organ("minio")
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """The compose MinIO, seen only as this case's scratch names: no road reaches a real bucket."""
    made: list[str] = []
    real = storage.list_derived_buckets
    monkeypatch.setattr(storage, "list_derived_buckets", lambda: [n for n in real() if n in made])
    yield made
    _drop(made)


def _drop(names: list[str]) -> None:
    """Empty (every version and marker) and remove each bucket; a failure warns, never raises."""
    client = storage.client()
    for name in names:
        try:
            if not _exists(name):
                continue
            storage._empty_and_remove(client, name)
        except Exception as failure:  # noqa: BLE001 - a teardown must not mask the case's own red
            warnings.warn(f"scratch bucket {name} left standing: {failure}", stacklevel=2)


def _make(store: list[str], name: str) -> str:
    storage.client().create_bucket(Bucket=name)
    store.append(name)
    return name


def _sweep(*args: str, stdin: str = "") -> str:
    out = io.StringIO()
    call_command("bucket_sweep", *args, stdin=io.StringIO(stdin), stdout=out)
    return out.getvalue()


def test_the_derivation_takes_any_path_and_this_checkout_is_one() -> None:
    assert storage.bucket_name_for(django_settings.BASE_DIR) == storage.derived_bucket_name()


def test_the_checkout_sweep_removes_its_own_buckets_and_no_stranger_s(
    store: list[str], tmp_path: Path, settings: Any
) -> None:
    settings.BASE_DIR = tmp_path / "gone-checkout"
    own = _make(store, storage.bucket_name_for(settings.BASE_DIR))
    worker = _make(store, f"{own}-gw0")
    storage.client().put_object(Bucket=worker, Key="t/x/left-behind", Body=b"x")
    stranger = _make(store, f"djb-stranger-{uuid.uuid4().hex[:8]}")

    printed = _sweep("--sweep")

    assert f"REMOVED  {own} " in printed
    assert f"REMOVED  {worker} " in printed
    assert not _exists(own)
    assert not _exists(worker)
    assert _exists(stranger)


def test_the_orphan_road_removes_only_what_a_handed_path_derives(
    store: list[str], tmp_path: Path
) -> None:
    dead = tmp_path / "dead-clone"
    dead.mkdir()
    live = tmp_path / "live-clone"
    orphan = _make(store, storage.bucket_name_for(dead))
    alive = _make(store, storage.bucket_name_for(live))
    stranger = _make(store, f"djb-stranger-{uuid.uuid4().hex[:8]}")
    handed = f"live {live}\nhanded {dead}\nhanded {live}\n"

    census = _sweep("--orphans", stdin=handed)
    assert f"  ORPHAN   {orphan} — derived from {dead}" in census
    assert f"  live     {alive} — {live}" in census
    assert f"  FOREIGN  {stranger} — " in census
    assert _exists(orphan)

    swept = _sweep("--orphans", "--sweep", stdin=handed)
    assert f"  REMOVED  {orphan} — derived from {dead}" in swept
    assert not _exists(orphan)
    assert _exists(alive)
    assert _exists(stranger)


def test_the_teardown_removes_a_scratch_bucket_that_still_holds_an_object(
    store: list[str],
) -> None:
    name = _make(store, f"djb-stranger-{uuid.uuid4().hex[:8]}")
    storage.client().put_object(Bucket=name, Key="t/x/left-behind", Body=b"x")
    _drop([name])
    assert not _exists(name)


def test_force_foreign_removes_a_bucket_no_root_derives_after_naming_it(
    store: list[str], tmp_path: Path
) -> None:
    live = tmp_path / "live-clone"
    live.mkdir()
    alive = _make(store, storage.bucket_name_for(live))
    stranger = _make(store, f"djb-stranger-{uuid.uuid4().hex[:8]}")
    storage.client().put_object(Bucket=stranger, Key="t/x/left-behind", Body=b"x")
    handed = f"live {live}\nhanded {live}\n"

    swept = _sweep(
        "--orphans", "--roots", str(tmp_path), "--sweep", "--force-foreign", stdin=handed
    )

    named = swept.index(f"  FOREIGN  {stranger} — ")
    assert swept.index(f"  REMOVED  {stranger} — FOREIGN") > named
    assert not _exists(stranger)
    assert _exists(alive)
    assert "buckets: 1 removed (1 foreign) · 0 orphan · 0 FOREIGN" in swept


def test_force_foreign_without_roots_is_refused_and_the_bucket_stands(
    store: list[str], tmp_path: Path
) -> None:
    stranger = _make(store, f"djb-stranger-{uuid.uuid4().hex[:8]}")

    out = io.StringIO()
    with pytest.raises(SystemExit) as refused:
        call_command(
            "bucket_sweep",
            "--orphans",
            "--sweep",
            "--force-foreign",
            stdin=io.StringIO(f"live {tmp_path}\n"),
            stdout=out,
        )

    assert refused.value.code == 2
    assert (
        "--force-foreign needs --roots <dir> — the census must have been given every place"
        " clones live" in out.getvalue()
    )
    assert _exists(stranger)


def test_a_live_bucket_stands_under_force_foreign(store: list[str], tmp_path: Path) -> None:
    live = tmp_path / "live-clone"
    live.mkdir()
    alive = _make(store, storage.bucket_name_for(live))
    worker = _make(store, f"{alive}-gw0")

    swept = _sweep(
        "--orphans",
        "--roots",
        str(tmp_path),
        "--sweep",
        "--force-foreign",
        stdin=f"live {live}\nhanded {live}\n",
    )

    assert _exists(alive)
    assert _exists(worker)
    assert "buckets: 0 removed (0 foreign) · 0 orphan · 0 FOREIGN" in swept


def test_force_foreign_against_a_store_that_cannot_be_asked_is_exit_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def unreadable() -> list[str]:
        raise storage.StorageUnreadable("the object store would not list its buckets: down")

    monkeypatch.setattr(storage, "list_derived_buckets", unreadable)
    out = io.StringIO()
    with pytest.raises(SystemExit) as refused:
        call_command(
            "bucket_sweep",
            "--orphans",
            "--roots",
            str(tmp_path),
            "--sweep",
            "--force-foreign",
            stdin=io.StringIO(f"live {tmp_path}\n"),
            stdout=out,
        )
    assert refused.value.code == 2
    assert "could not look: buckets" in out.getvalue()


def test_the_seam_refuses_a_forced_removal_handed_no_root(store: list[str]) -> None:
    stranger = _make(store, f"djb-stranger-{uuid.uuid4().hex[:8]}")

    with pytest.raises(ValueError, match="--force-foreign needs --roots"):
        storage.remove_foreign_buckets([stranger], roots=[])

    assert _exists(stranger)


def test_the_seam_skips_a_name_no_longer_standing(store: list[str], tmp_path: Path) -> None:
    gone = f"djb-stranger-{uuid.uuid4().hex[:8]}"

    assert storage.remove_foreign_buckets([gone], roots=[tmp_path]) == []
