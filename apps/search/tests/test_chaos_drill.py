"""The chaos drill: **stop the organ, drive it, start it, drive it again.**

ADR search-2 makes this a criterion rather than an ops aspiration, and this
module is that criterion: a real Meilisearch, really stopped, mid-suite, with
the door driven over the wire on both sides of the outage and on both sides of
the recovery. Everything else in `test_degradation.py` proves the circuit
against a double; nothing there can prove that the *client* raises what the
circuit catches when a real server stops answering, which is the one link in the
chain a double is standing in for.

## Why this starts its OWN container instead of stopping the compose one

Because the compose stack is shared. `compose.yaml` declares `name:
djangobootstrap`, every checkout on this machine points at the one
`meilisearch` service on 7700, and worktrees gate in parallel — so
`docker stop djangobootstrap-meilisearch-1` inside a test is `pkill -f pytest`
in another costume: it would redden a peer's run, from a process that peer
cannot see, for a reason its log would not explain. The standing rule is to kill
only your own children, and it does not stop being true because the child is a
container.

So the drill runs `docker run` for a Meilisearch of its own, on an ephemeral
port, from **the image `compose.yaml` pins** (read out of that file rather than
spelled here, so the drill can never test a version the product does not ship),
points `settings.MEILI_URL` at it for the duration, and stops and starts THAT.
The organ is real, the stop is a real `docker stop`, and no other agent's tree
is touched.

Settings and not the environment: `engine.py` reads
`settings.MEILI_URL`/`MEILI_MASTER_KEY` now, so a test that wants a particular
engine says so where the engine is listening.

The container is torn down by id in a `finally`, and the fixture carries
`@organ("meili")` — so every test here is derived into the slow tier and runs at
push against the real stack, never in a builder's `--loop`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from apps.conftest import organ
from apps.events.models import Event
from apps.search import engine as engine_module
from apps.search import registry, selectors
from apps.search.activities import document_for
from apps.search.events import SEARCH_ENGINE_DEGRADED, SEARCH_ENGINE_RECOVERED
from apps.search.types import Searchable

from .conftest import WIDGETS, World

pytestmark = pytest.mark.django_db

SEARCH_URL = "/api/v1/search/"

#: How long the drill's own cooldown is. One second rather than the production
#: thirty, so "within one TTL the engine field reads meili again" is a criterion
#: this test asserts rather than a criterion it waits out. The production value
#: is asserted separately, below, so shortening it here cannot quietly become
#: shortening it everywhere.
DRILL_COOLDOWN_SECONDS = 1

#: How long to wait for a Meilisearch to answer `/health` after a start.
HEALTH_TIMEOUT_SECONDS = 30.0

#: `docker stop -t` — Meilisearch handles SIGTERM promptly and the default ten
#: seconds is ten seconds of nothing happening on every run of this drill.
STOP_GRACE_SECONDS = 1

#: How long to wait for Docker to publish the container's port mapping.
#: The mapping appears in milliseconds when it appears at all, so five seconds
#: is two orders of magnitude of headroom and still inside a test's patience.
PORT_TIMEOUT_SECONDS = 5.0

#: How often to ask while waiting. Short enough that the healthy case pays
#: nothing measurable, long enough not to fork fifty `docker` processes a second.
PORT_POLL_SECONDS = 0.05


@dataclass
class Chaos:
    """One Meilisearch this test owns, and the two verbs it exists to be given.

    **The address is re-read after every start, never remembered**, and both
    halves of that were measured rather than reasoned:

    1. Docker re-publishes an ephemeral port on `docker start`, so the recovery
       leg came back on a different port from the one the drill was pointed at
       and a container that had just come up healthy read as still dead.
    2. Hand-picking a free port instead traded that for a worse bug: pytest runs
       `-n auto`, two workers each asked the kernel for a port in the window
       between bind-and-close and `docker run`, and the second `docker run`
       died with exit 125, *port is already allocated* — a flake that only
       appears under parallelism, which is how the whole suite runs.

    So Docker chooses, and this asks it what it chose, every time.
    `settings.MEILI_URL` is re-pointed on each start — a SETTING and not the
    environment: `engine.meili_url()` reads settings now, so
    that is where a test that wants a particular engine says which one.
    """

    container: str
    settings: Any
    url: str = ""

    def point_at_it(self) -> None:
        self.url = f"http://127.0.0.1:{_published_port(self.container)}"
        self.settings.MEILI_URL = self.url
        _await_health(self.url)

    def stop(self) -> None:
        _docker("stop", "-t", str(STOP_GRACE_SECONDS), self.container)

    def start(self) -> None:
        _docker("start", self.container)
        self.point_at_it()


def _docker(*args: str, check: bool = True) -> str:
    out = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=120
    )
    return out.stdout.strip()


def _published_port(container: str) -> str:
    """The host port Docker mapped to 7700 — **polled until Docker will say it**.

    `docker start` returns as soon as the container is started, and publishing
    the port mapping is not part of what it waits for. So there is a window,
    short and load-dependent, in which the container is running and
    `docker port` has nothing to report — and the drill asked in exactly that
    window.

    **Three sightings** (a contended machine, a quiet one, and the
    pre-push full gate): `docker port <container> 7700/tcp` returned an empty
    string, `"".splitlines()` is `[]`, and `[0]` was an `IndexError` that killed
    the test. A flake in a test whose whole subject is a container being stopped
    and started is the worst possible place for one: it reads as the drill
    catching something.

    **Two shapes, not one**, and the second is why this does not simply guard
    the index. `docker port` **exits 1** — "No public port '7700/tcp' published"
    — when it has no mapping, which under `check=True` is a
    `CalledProcessError` rather than an empty string. Measured here rather than
    read off a doc page: whether an unpublished port comes back as exit 0 with
    no output or exit 1 with a message is not something to leave to luck when
    the whole point is to stop guessing about a race. Both are the same fact —
    Docker has not published it yet — and both are polled through.

    A five-second ceiling: the mapping appears in milliseconds when it appears
    at all, so this is two orders of magnitude of headroom and still fails
    inside a test's patience. It fails with a sentence naming what never
    appeared, because the whole cost of the original defect was that
    `IndexError: list index out of range` names nothing.
    """
    deadline = time.monotonic() + PORT_TIMEOUT_SECONDS
    last = ""
    while time.monotonic() < deadline:
        try:
            last = _docker("port", container, "7700/tcp", check=False)
        except subprocess.SubprocessError as unavailable:  # pragma: no cover - docker gone
            last = str(unavailable)
        lines = last.splitlines()
        if lines and ":" in lines[0]:
            return lines[0].rsplit(":", 1)[1]
        time.sleep(PORT_POLL_SECONDS)
    raise AssertionError(
        f"docker never published a host port for 7700/tcp on container {container!r} "
        f"within {PORT_TIMEOUT_SECONDS:.0f}s. `docker start` returns before the mapping "
        f"exists, so this is that window failing to close rather than a mapping that is "
        f"wrong — the last thing `docker port` said was {last!r}. Check that the "
        "container is still running (`docker ps -a`) before suspecting the drill."
    )


def _pinned_image() -> str:
    """The Meilisearch image `compose.yaml` pins. **Read, never re-spelled.**

    A literal here would be a second pin, and the failure mode of a second pin
    is the quiet one: the drill goes on proving the circuit against v1.53 for a
    year after the product moved, and the version-specific behaviour it exists
    to prove (which exception the client raises when the server is gone) is
    exactly the sort of thing a version changes.
    """
    root = Path(__file__).resolve().parents[3]
    text = (root / "compose.yaml").read_text(encoding="utf-8")
    found = re.search(r"^\s*image:\s*(getmeili/meilisearch:\S+)\s*$", text, re.MULTILINE)
    assert found, "compose.yaml no longer pins a getmeili/meilisearch image"
    return found.group(1)


def _await_health(url: str) -> None:
    """Poll Meilisearch's own unauthenticated `/health` until it answers."""
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as answer:
                if answer.status == 200:
                    return
        except (urllib.error.URLError, OSError, TimeoutError) as error:  # noqa: PERF203
            last = error
        time.sleep(0.2)
    raise AssertionError(f"the drill's Meilisearch never became healthy at {url}: {last}")


@pytest.fixture
@organ("meili")
def chaos(monkeypatch: pytest.MonkeyPatch, settings: Any, live_meili: str) -> Iterator[Chaos]:
    """A Meilisearch of our own, on an ephemeral port, torn down by id.

    `settings.MEILI_URL` is pointed at it for the duration, which is what
    `engine.meili_url()` reads — so the fenced module reaches the drill's
    container exactly the way it reaches the deployment's, with no branch
    anywhere for "in a test".

    It takes `live_meili` for the skip and for the credential: this drill runs
    only where the compose organ is configured, and its own container is started
    with that same master key, so the client's credential is the deployment's
    rather than a second one the test invented.
    """
    if shutil.which("docker") is None:
        pytest.skip("no docker — the chaos drill needs a container it can stop")

    key = settings.MEILI_MASTER_KEY
    container = _docker(
        "run",
        "-d",
        "--publish",
        "127.0.0.1::7700",
        "--env",
        f"MEILI_MASTER_KEY={key}",
        "--env",
        "MEILI_ENV=development",
        "--env",
        "MEILI_NO_ANALYTICS=true",
        _pinned_image(),
    )
    try:
        chaos = Chaos(container=container, settings=settings)
        chaos.point_at_it()
        monkeypatch.setattr(selectors, "COOLDOWN_SECONDS", DRILL_COOLDOWN_SECONDS)
        yield chaos
    finally:
        # By id, always, and `-f` because the drill may have left it stopped.
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


@pytest.fixture
def indexed(chaos: Chaos, world: World, monkeypatch: pytest.MonkeyPatch) -> str:
    """One kind, declared and really indexed into the drill's own Meilisearch.

    A per-test label for the reason `live_label` gives: the index prefix is
    derived from `DATABASE_NAME`, which every xdist worker in a checkout shares.
    """
    label = f"drill{uuid4().hex[:12]}"
    declaration = Searchable(
        model=WIDGETS.model, label=label, fields=[("name", "A")], display="name"
    )
    monkeypatch.setattr(registry, "declarations", lambda: (declaration,))
    live = engine_module.engine()
    live.apply_settings(declaration=declaration, digest="drill")
    rows = list(declaration.model._default_manager.filter(tenant=world.tenant))
    assert rows, "the world fixture committed no widgets — this drill could not fail"
    live.upsert(label=label, documents=[document_for(declaration, row) for row in rows])
    return label


def _said(world: World) -> list[str]:
    return [
        name
        for name in Event.objects.filter(tenant=world.tenant)
        .order_by("created_at")
        .values_list("name", flat=True)
        if name.startswith("search.")
    ]


def test_the_production_cooldown_is_the_one_the_drill_shortens() -> None:
    """The drill shortens a real constant, not a test-only one.

    Without this, `DRILL_COOLDOWN_SECONDS` could drift into being the only value
    anybody exercises, and the production TTL would be a number no test has ever
    seen expire.
    """
    assert selectors.COOLDOWN_SECONDS == 30
    assert DRILL_COOLDOWN_SECONDS < selectors.COOLDOWN_SECONDS


def test_stopping_the_index_degrades_and_starting_it_recovers(
    api: Any, world: World, chaos: Chaos, indexed: str
) -> None:
    """The whole drill, in one test, because the halves only mean anything together.

    Down: `200` with pg-ranked hits and `engine="postgres"`, zero 5xx, and
    `search.engine.degraded` on the spine — once, no matter how many requests
    meet the outage. Up: within one cooldown TTL the engine field reads `meili`
    again and `search.engine.recovered` closes the pair.

    Every leg goes through the REST door rather than through the selector, so
    "zero 5xx" is a statement about what a client received.
    """
    api.force_login(world.owner)

    # --- healthy: the real index answers, and says so ------------------------
    healthy = api.get(SEARCH_URL, {"q": "Widget", "kinds": indexed})
    assert healthy.status_code == 200, healthy.content
    assert healthy.json()["engine"] == "meili"
    from_index = {hit["id"] for hit in healthy.json()["items"]}
    assert from_index, "the drill's index answered nothing — the rest proves nothing"
    assert _said(world) == []

    # --- the outage ----------------------------------------------------------
    chaos.stop()

    degraded = api.get(SEARCH_URL, {"q": "Widget", "kinds": indexed})
    assert degraded.status_code == 200, degraded.content
    body = degraded.json()
    assert body["engine"] == "postgres"
    assert {hit["id"] for hit in body["items"]} == from_index, (
        "the fallback found a different set of rows than the index did — what you "
        "can see is exactly what must not change across a failover"
    )
    assert _said(world) == [SEARCH_ENGINE_DEGRADED]

    # --- and it stays one announcement, and one dead round trip --------------
    for _ in range(3):
        again = api.get(SEARCH_URL, {"q": "Widget", "kinds": indexed})
        assert again.status_code == 200, again.content
        assert again.json()["engine"] == "postgres"
    assert _said(world) == [SEARCH_ENGINE_DEGRADED]

    # --- recovery ------------------------------------------------------------
    chaos.start()
    time.sleep(DRILL_COOLDOWN_SECONDS + 0.5)

    recovered = api.get(SEARCH_URL, {"q": "Widget", "kinds": indexed})
    assert recovered.status_code == 200, recovered.content
    assert recovered.json()["engine"] == "meili"
    assert {hit["id"] for hit in recovered.json()["items"]} == from_index
    assert _said(world) == [SEARCH_ENGINE_DEGRADED, SEARCH_ENGINE_RECOVERED]

    # And a healthy request after the recovery says nothing at all.
    api.get(SEARCH_URL, {"q": "Widget", "kinds": indexed})
    assert _said(world) == [SEARCH_ENGINE_DEGRADED, SEARCH_ENGINE_RECOVERED]

    engine_module.engine().drop_index(uid=engine_module.index_name(indexed))


def test_the_announcements_carry_the_engine_names_an_operator_reads(
    api: Any, world: World, chaos: Chaos, indexed: str
) -> None:
    """The payload says which engine went and which one took over — and nothing else.

    An index uid or a client's error string here would put this deployment's
    infrastructure vocabulary on a customer's webhook. The reason lives in the
    structured log line the circuit writes, where operators are.
    """
    api.force_login(world.owner)
    chaos.stop()
    assert api.get(SEARCH_URL, {"q": "Widget", "kinds": indexed}).status_code == 200

    event = Event.objects.get(tenant=world.tenant, name=SEARCH_ENGINE_DEGRADED)
    payload = event.payload if isinstance(event.payload, dict) else json.loads(event.payload)
    assert payload["engine"] == "meili"
    assert payload["serving"] == "postgres"
    assert indexed not in json.dumps(payload)

    chaos.start()
    engine_module.engine().drop_index(uid=engine_module.index_name(indexed))


#: The two things `docker port` does when it has no mapping to report, as the
#: fake below produces them. **Both were measured on this tree**, and having
#: both is the point: the sighting reported empty stdout, and asking a real
#: container for a port it does not publish exits 1 instead — so a guard that
#: only defended the `[0]` index would have left half the race open.
def _says_nothing(*args: str, **kwargs: Any) -> str:
    """Shape A: exit 0, empty stdout. `"".splitlines()[0]` was the IndexError."""
    return ""


def _refuses(*args: str, **kwargs: Any) -> str:
    """Shape B: exit 1, "No public port published". A `CalledProcessError`."""
    raise subprocess.CalledProcessError(1, ["docker", "port"], stderr="No public port")


@pytest.mark.parametrize(("name", "docker"), [("empty", _says_nothing), ("refusal", _refuses)])
def test_a_port_docker_will_not_name_is_a_named_failure(
    monkeypatch: pytest.MonkeyPatch, name: str, docker: Any
) -> None:
    """Held shut. **The race is not reproducible; its two shapes are.**

    Three sightings were recorded — a contended machine, a quiet one, and the
    pre-push full gate — and none can be summoned on demand: it needs
    `docker port` to be asked inside the window between `docker start`
    returning and the mapping existing. A test that tried to win that race
    would be a second flake pointed at the first, so **this drives the shape
    rather than the timing**, and says so.

    A first attempt drove it against the real compose container asking for a
    port it does not publish. That was wrong twice over and is recorded because
    the correction is the useful part: `djangobootstrap-meilisearch-1` **does**
    publish 7700, so the drive did not fail at all (`DID NOT RAISE`), and even
    had it worked it would have coupled a unit-shaped assertion to whatever the
    shared compose stack happens to map today. The fake is the honest
    instrument: it produces exactly what Docker produces, and it produces both.

    Before the fix these were `IndexError: list index out of range` and
    `CalledProcessError` — neither of which names the container, the port, or
    the fact that Docker simply had not got there yet.
    """
    monkeypatch.setattr("apps.search.tests.test_chaos_drill.PORT_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr("apps.search.tests.test_chaos_drill._docker", docker)

    with pytest.raises(AssertionError) as never_appeared:
        _published_port("some-drill-container")

    said = str(never_appeared.value)
    assert "never published a host port" in said
    assert "some-drill-container" in said, "the failure does not name the container"
    assert "7700/tcp" in said, "the failure does not name the port that never appeared"


def test_the_poll_returns_the_port_when_docker_has_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half, so the test above cannot pass by the poll always failing.

    A `docker port` that answers must be parsed into the host port and nothing
    else — the line is `0.0.0.0:32768` or `[::]:32768` and it is the tail that
    matters, which is why the split is from the right.
    """
    monkeypatch.setattr(
        "apps.search.tests.test_chaos_drill._docker",
        lambda *args, **kwargs: "0.0.0.0:32768\n[::]:32768",
    )
    assert _published_port("whatever") == "32768"
