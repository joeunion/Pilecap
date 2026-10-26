"""The identity home live: a killed worker's run resumed, then a customer signing in at two hosts.

does-not-cover: the customer persona's `PortalRequest` step — no case drives it.
does-not-cover: the platform's pages' DOM — redirects, cookies and the wire are read.
does-not-cover: the `hosted` door's road (the platform's own invite page).
does-not-cover: a SIGKILL of this module: the database goes to the sweep, realms and mail to nobody.
does-not-cover: a kill at any other point of the activity than the one marker between two calls.
does-not-cover: Temporal's UI — the resume is read off the home row and the platform.
does-not-cover: a change the `drives` marker does not name (`create_tenant`, `invite_member`, …).
does-not-cover: the Zitadel project per xdist worker (`identity-home drive f6<worker>`) is kept.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from quality.could_not_look import CouldNotLook

pytestmark = pytest.mark.drives(
    "apps/accounts/workflows.py",
    "apps/accounts/activities.py",
    "apps/accounts/realm.py",
    "apps/accounts/realms",
    "apps/accounts/zitadel.py",
    "apps/accounts/types.py",
    "apps/core/templates/mail",
    "apps/accounts/adapter.py",
    "apps/accounts/signin.py",
    "apps/accounts/views.py",
    "apps/accounts/migrations",
    "apps/accounts/management/commands/zitadel_audit.py",
    "apps/accounts/management/commands/zitadel_reconcile.py",
    "apps/accounts/management/commands/zitadel_seed.py",
    "apps/example_portal/surfaces.py",
    "manage.py",
    "scripts/db.sh",
    "scripts/gate_refuse.sh",
)

ROOT = Path(__file__).resolve().parents[2]
MAILPIT = "http://127.0.0.1:8025"
STAFF_HOST = "localhost"
CUSTOMER_HOST = "customer.localhost"
MARKER = "accounts.zitadel.organization_ensured"
PROLOGUE = """import os, sys, time
import django


def _drive_names_the_cause(kind, value, tb):
    print("!! " + kind.__name__ + ": " + str(value), file=sys.stderr, flush=True)
    sys.__excepthook__(kind, value, tb)


sys.excepthook = _drive_names_the_cause
django.setup()
"""
WATCHER = """
import os, signal, sys, time
log, needle, name, pid = sys.argv[1], sys.argv[2].encode(), sys.argv[3].encode(), int(sys.argv[4])
started = time.monotonic()
with open(log, "rb") as fh:
    seen = b""
    while time.monotonic() - started < 180:
        seen += fh.read()
        for line in seen.split(b"\\n"):
            if needle in line and name in line:
                os.kill(pid, signal.SIGKILL)
                print(f"killed={pid}", flush=True)
                print(f"after={time.monotonic() - started:.3f}", flush=True)
                sys.exit(0)
        seen = seen[seen.rfind(b"\\n") + 1:]
        time.sleep(0.002)
print("killed=", flush=True)
"""
REALM_STATE = """
from django.conf import settings

from apps.accounts import zitadel
from apps.accounts.models import IdentityHome
from apps.accounts.realms.zitadel import realm_name
from apps.core.models import Tenant

tenant = Tenant.objects.get(slug=sys.argv[1])
home = IdentityHome.objects.for_tenant(tenant).first()
print(f"state={home.state if home else 'none'}")
org = zitadel.find_organization(name=realm_name(tenant))
print(f"org={org['id'] if org else ''}")
project = zitadel.find_project(name=settings.ZITADEL_PROJECT_NAME)
grant = zitadel.project_grant(project_id=str(project["id"]), org_id=str(org["id"])) if org else None
print(f"grant={(grant or {}).get('state', '')}")
named = [one for one in zitadel.organizations() if one.get("name") == realm_name(tenant)]
print(f"orgs_named={len(named)}")
print(f"realm_name={realm_name(tenant)}")
"""
WAIT_HOME = """
from apps.accounts.models import IdentityHome
from apps.core.models import Tenant

tenant = Tenant.objects.get(slug=sys.argv[1])
started = time.monotonic()
state = "none"
while time.monotonic() - started < float(sys.argv[2]):
    home = IdentityHome.objects.for_tenant(tenant).first()
    state = home.state if home else "none"
    if state == IdentityHome.State.OWN_ORG:
        break
    time.sleep(1)
print(f"state={state}")
print(f"waited={time.monotonic() - started:.0f}")
"""
JOIN_ROWS = """
from apps.accounts.models import IdentityHome, SsoIdentity, User
from apps.core.models import Tenant

user = User.objects.filter(email=sys.argv[1]).first()
home = IdentityHome.objects.for_tenant(Tenant.objects.get(slug=sys.argv[2])).first()
print(f"realm_a={home.realm_id if home else ''}")
rows = list(SsoIdentity.objects.filter(user=user)) if user else []
print(f"rows={len(rows)}")
for row in rows:
    print(f"row={row.realm} connection={row.connection_id or 'none'}")
realm = home.realm_id if home else None
in_a = sum(1 for row in rows if row.realm == realm and row.connection_id is None)
print(f"in_a={in_a}")
"""
PROJECT_IDS = """
from django.conf import settings

from apps.accounts import zitadel

project = zitadel.find_project(name=settings.ZITADEL_PROJECT_NAME)
if project is None:
    name = settings.ZITADEL_PROJECT_NAME
    print(f"!! the seed ran and Zitadel holds no project named {name!r}", file=sys.stderr)
    sys.exit(2)
app = settings.ZITADEL_BROWSER_APP_NAME
browser = zitadel.find_application(project_id=str(project["id"]), name=app) or {}
client_id = str((browser.get("oidcConfig") or {}).get("clientId", ""))
if not client_id:
    print(f"!! no browser client id: project {project['id']} has no OIDC app", file=sys.stderr)
    sys.exit(2)
print(f"project={project['id']}")
print(f"client_id={client_id}")
"""
REACHABLE = """
from apps.accounts import zitadel

if not zitadel.configured():
    print("!! no Zitadel: ZITADEL_ISSUER and ZITADEL_PAT are not both set", file=sys.stderr)
    sys.exit(2)
try:
    org = zitadel.organization()
except zitadel.ZitadelError as error:
    said = f"!! no Zitadel: {zitadel.issuer()} refused the machine credential ({error})"
    print(said, file=sys.stderr)
    sys.exit(2)
print(f"issuer={zitadel.issuer()}")
"""
MODEL = """
try:
    from apps.accounts.models import IdentityHome  # noqa: F401
except ImportError:
    print("!! no `IdentityHome` model — the identity home has not landed", file=sys.stderr)
    sys.exit(2)
print("model=present")
"""
REMOVE_REALMS = """
from apps.accounts import zitadel
for org_id in sorted(set(open(sys.argv[1]).read().split())):
    zitadel.remove_organization(org_id=org_id)
"""


def the_cause_in(path: Path) -> str:
    """A dead process's cause: its first `!!` line, else its LAST non-blank line."""
    lines = path.read_text(errors="replace").splitlines() if path.is_file() else []
    for line in lines:
        if line.lstrip().startswith("!!"):
            return line.lstrip()[2:].strip()
    said = [line.strip() for line in lines if line.strip()]
    return said[-1] if said else ""


def refusal(why: str, cause: str) -> CouldNotLook:
    """`why`, then the cause the process named, as one could-not-look."""
    return CouldNotLook(f"{why}{f' — {cause}' if cause else ''}")


@dataclass
class Steps:
    """Django steps under one interpreter and environment; each writes `key=value` lines."""

    pybin: str
    env: dict[str, str]
    work: Path
    count: int = 0
    last_err: Path = Path()

    def run(self, label: str, program: str, *args: str) -> dict[str, str]:
        """One step; its last value per key, or `CouldNotLook` naming the step and its cause."""
        self.count += 1
        out, self.last_err = self.work / f"py-{self.count}.out", self.work / f"py-{self.count}.err"
        with out.open("wb") as o, self.last_err.open("wb") as e:
            rc = subprocess.run(
                [self.pybin, "-c", PROLOGUE + program, *args],
                cwd=ROOT,
                stdout=o,
                stderr=e,
                stdin=subprocess.DEVNULL,
                env=self.env,
            ).returncode
        if rc != 0:
            raise refusal(f"the step '{label}' exited {rc}", the_cause_in(self.last_err))
        values: dict[str, str] = {}
        for line in out.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep:
                values[key] = value
        values["_out"] = out.read_text()
        return values

    def manage(self, label: str, *args: str) -> tuple[int, str]:
        """A management command, its status and its whole output."""
        self.count += 1
        out = self.work / f"manage-{self.count}-{label}.out"
        with out.open("wb") as sink:
            rc = subprocess.run(
                [self.pybin, "manage.py", *args],
                cwd=ROOT,
                stdout=sink,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=self.env,
            ).returncode
        return rc, out.read_text(errors="replace")

    def must(self, label: str, *args: str) -> str:
        """A management command that has to succeed; could-not-look naming its cause otherwise."""
        rc, text = self.manage(label, *args)
        if rc != 0:
            (self.work / "must.out").write_text(text)
            raise refusal(
                f"manage.py {args[0]} ({label}) exited {rc}", the_cause_in(self.work / "must.out")
            )
        return text


def start_worker(pybin: str, env: dict[str, str], log: Path) -> subprocess.Popen[bytes]:
    """The worker as its own interpreter, once it logs that it started; or its own cause."""
    with log.open("wb") as sink:
        worker = subprocess.Popen(
            [pybin, "-m", "apps.workflows.worker"],
            cwd=ROOT,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env=env,
        )
    for _ in range(900):
        if '"workflows.worker.started"' in log.read_text(errors="replace"):
            return worker
        if worker.poll() is not None:
            raise refusal(
                f"no worker: the worker (pid {worker.pid}) exited before it polled"
                " — no Temporal to poll?",
                the_cause_in(log),
            )
        time.sleep(0.1)
    worker.kill()
    raise CouldNotLook(f"no worker: pid {worker.pid} logged no workflows.worker.started in 90 s")


def stop(process: subprocess.Popen[bytes] | None) -> None:
    """TERM one owned process and reap it."""
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait()


def db(*command: str, env: dict[str, str]) -> int:
    """One `scripts/db.sh` function under `env`, its status."""
    return subprocess.run(
        ["bash", "-c", 'source scripts/db.sh >/dev/null 2>&1 && "$@"', "db", *command],
        cwd=ROOT,
        capture_output=True,
        env=env,
    ).returncode


def mailpit(path: str, method: str = "GET", body: bytes | None = None) -> object:
    """One Mailpit API call, its JSON (None for an answer that is not a document)."""
    request = urllib.request.Request(f"{MAILPIT}{path}", data=body, method=method)  # noqa: S310 — MAILPIT is the compose-local http mail catcher
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=10) as answer:  # noqa: S310 — MAILPIT is the compose-local http mail catcher
        raw = answer.read()
    return json.loads(raw) if raw[:1] in (b"{", b"[") else None


def host_of(url: str) -> str:
    """The host a URL names."""
    return urlsplit(url).hostname or ""


@dataclass
class Live:
    """The module's world: its database, project, tenants, processes and the browser's jar."""

    steps: Steps
    env: dict[str, str]
    work: Path
    port: int
    slug_a: str
    slug_b: str
    worker: subprocess.Popen[bytes] | None = None
    worker_log: Path = Path()
    workers: int = 0
    server: subprocess.Popen[bytes] | None = None
    realms: list[str] = field(default_factory=list)
    mail_ids: list[str] = field(default_factory=list)
    password: str = ""
    status: str = ""
    location: str = ""

    @property
    def customer(self) -> str:
        return f"customer.{self.slug_a}@example.com"

    @property
    def jar(self) -> Path:
        return self.work / "browser.jar"

    def start_worker(self) -> None:
        """A new worker on this world's queue."""
        self.workers += 1
        self.worker_log = self.work / f"worker-{self.workers}.log"
        self.worker = start_worker(self.steps.pybin, self.env, self.worker_log)

    def start_server(self) -> None:
        """uvicorn on the free port, once the staff host answers."""
        log = self.work / "server.log"
        with log.open("wb") as sink:
            self.server = subprocess.Popen(
                [
                    self.steps.pybin,
                    "-m",
                    "uvicorn",
                    "config.asgi:application",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.port),
                ],
                cwd=ROOT,
                stdout=sink,
                stderr=subprocess.STDOUT,
                env=self.env,
            )
        for _ in range(600):
            self.browse("GET", f"http://{STAFF_HOST}:{self.port}/accounts/login/", jar=False)
            if self.status != "000":
                return
            if self.server.poll() is not None:
                raise refusal(
                    f"the server (pid {self.server.pid}) exited before it answered",
                    the_cause_in(log),
                )
            time.sleep(0.1)
        raise CouldNotLook(f"the server on port {self.port} did not answer in 60 s")

    def browse(self, method: str, url: str, *args: str, jar: bool = True) -> None:
        """One request, never followed: `status`, `location`, and the body in `work/body`."""
        cookies = ["-c", str(self.jar), "-b", str(self.jar)] if jar else []
        done = subprocess.run(
            [
                "curl",
                "-s",
                "-X",
                method,
                *cookies,
                "-o",
                str(self.work / "body"),
                "-w",
                "%{http_code} %{redirect_url}",
                *args,
                url,
            ],
            capture_output=True,
            text=True,
        )
        line = done.stdout if done.returncode == 0 else "000 "
        self.status, _, self.location = line.partition(" ")

    def cookie(self, host: str, name: str) -> str:
        """A cookie the jar holds for exactly that host."""
        found = ""
        for line in self.jar.read_text().splitlines() if self.jar.is_file() else []:
            cells = line.split("\t")
            if len(cells) >= 7 and cells[0].removeprefix("#HttpOnly_") == host and cells[5] == name:
                found = cells[6]
        return found

    def post_form(self, url: str, host: str, *fields: str) -> None:
        """A form POST carrying the host's CSRF token."""
        data = ["--data-urlencode", f"csrfmiddlewaretoken={self.cookie(host, 'csrftoken')}"]
        for one in fields:
            data += ["--data-urlencode", one]
        self.browse("POST", url, *data)

    def body(self) -> str:
        """The last response's body."""
        path = self.work / "body"
        return path.read_text(errors="replace") if path.is_file() else ""

    def realm_state(self, slug: str) -> dict[str, str]:
        return self.steps.run(f"the realm of {slug}", REALM_STATE, slug)

    def wait_home(self, slug: str, seconds: int) -> dict[str, str]:
        return self.steps.run(f"the home of {slug}", WAIT_HOME, slug, str(seconds))

    def join_rows(self) -> dict[str, str]:
        return self.steps.run("the join rows", JOIN_ROWS, self.customer, self.slug_a)

    def create_tenant(self, slug: str) -> None:
        program = (
            "from apps.core.actor import system_actor\n"
            "from apps.core.services import create_tenant\n"
            f"create_tenant(name='Identity home drive {slug}', slug='{slug}',"
            " actor=system_actor())\n"
        )
        self.steps.must(f"create {slug}", "shell", "-c", program)

    def invite_customer(self) -> None:
        program = (
            "from apps.core.actor import system_actor\nfrom apps.core.models import Tenant\n"
            "from apps.core.services import invite_member\n"
            f"tenant = Tenant.objects.get(slug='{self.slug_a}')\n"
            f"invite_member(tenant=tenant, email='{self.customer}', role='customer',"
            " actor=system_actor(tenant=tenant))\n"
        )
        self.steps.must(f"invite into {self.slug_a}", "shell", "-c", program)

    def latest_mail(self, want: int) -> tuple[str, list[str]]:
        """Waits for the customer to hold `want` mails; the newest's text and its links."""
        for _ in range(121):
            found = mailpit(f"/api/v1/search?query=to:{self.customer}")
            assert isinstance(found, dict)
            if int(found.get("messages_count", 0)) >= want:
                break
            time.sleep(1)
        else:
            raise CouldNotLook(
                f"Mailpit holds fewer than {want} message(s) for {self.customer} after 120 s"
            )
        self.mail_ids += [str(m["ID"]) for m in found["messages"]]
        message = mailpit(f"/api/v1/message/{found['messages'][0]['ID']}")
        assert isinstance(message, dict)
        text = str(message.get("Text", ""))
        return text, [word for word in text.split() if word.startswith(("http://", "https://"))]


def dot_env_keys() -> set[str]:
    """The names `.env` declares, which the settings import loaded and no shell caller has."""
    path = ROOT / ".env"
    lines = path.read_text().splitlines() if path.is_file() else []
    return {
        line.split("=", 1)[0].strip() for line in lines if "=" in line and not line.startswith("#")
    }


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Live]:
    """The world, made once per worker; each precondition is could-not-look, never a pass."""
    for tool in ("uv", "curl"):
        if shutil.which(tool) is None:
            raise CouldNotLook(f"no {tool} on PATH")
    work = tmp_path_factory.mktemp("idhome")
    named = subprocess.run(
        ["uv", "run", "python", "-c", "import sys; print(sys.executable)"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    pybin = named.stdout.strip()
    if named.returncode != 0 or not os.access(pybin, os.X_OK):
        raise CouldNotLook(f"uv could not name this checkout's interpreter: {named.stderr[:300]}")
    strip = dot_env_keys() | {"DJANGO_SETTINGS_MODULE", "DATABASE_NAME_SOURCE"}
    env = {k: v for k, v in os.environ.items() if k not in strip and not k.startswith("PYTEST_")}
    base = subprocess.run(
        ["bash", "-c", "source scripts/db.sh >/dev/null 2>&1 && db_name"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()
    if not base:
        raise CouldNotLook("scripts/db.sh could not derive this checkout's database name")
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    env.update(
        DATABASE_NAME=f"{base}_f6{worker}_idhome",
        DJANGO_SETTINGS_MODULE="config.settings.local",
        DJB_SIGN_IN_DOOR="ours",
        SURFACE_HOSTS=f"staff={STAFF_HOST},customer={CUSTOMER_HOST}",
        ZITADEL_PROJECT_NAME=f"identity-home drive f6{worker}",
        TEMPORAL_MACHINERY_LIFETIME="process",
        PYTHONUNBUFFERED="1",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="127.0.0.1",
        EMAIL_PORT="1025",
        EMAIL_HOST_USER="",
        EMAIL_HOST_PASSWORD="",
        EMAIL_USE_TLS="0",
    )
    steps = Steps(pybin, env, work)
    steps.run("identity-home model", MODEL)
    steps.run("Zitadel reachability", REACHABLE)
    try:
        mailpit("/api/v1/info")
    except OSError as error:
        raise CouldNotLook(f"no Mailpit: {MAILPIT}/api/v1/info did not answer ({error})") from error
    try:
        found = {row[4][0] for row in socket.getaddrinfo(CUSTOMER_HOST, None)}
    except OSError as error:
        raise CouldNotLook(
            f"no second host: {CUSTOMER_HOST} does not resolve on this machine ({error})"
        ) from error
    if not found & {"127.0.0.1", "::1"}:
        raise CouldNotLook(
            f"no second host: {CUSTOMER_HOST} resolves to {sorted(found)}, not to this machine"
        )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env["PUBLIC_BASE_URL"] = f"http://{STAFF_HOST}:{port}"
    tag = hashlib.sha256(f"{work}{time.time()}".encode()).hexdigest()[:6]
    world = Live(steps, env, work, port, f"idh{tag}a", f"idh{tag}b")
    made = False
    try:
        if db("db_exists", env["DATABASE_NAME"], env=env) == 0:
            db("db_drop", env["DATABASE_NAME"], env=env)
        if db("db_create", env["DATABASE_NAME"], env=env) != 0:
            raise CouldNotLook(f"could not create the module's database {env['DATABASE_NAME']}")
        made = True
        steps.must("migrate", "migrate", "--no-input")
        rc, seeded = steps.manage("seed", "zitadel_seed", "--skip-user", "--rotate-web-secret")
        lines = seeded.splitlines()
        marks = [i for i, line in enumerate(lines) if "rotated browser secret" in line]
        secret = (
            next((line.split()[1] for line in lines[marks[0] + 1 :] if "clientSecret:" in line), "")
            if marks
            else ""
        )
        if rc != 0 or not secret:
            raise CouldNotLook(
                f"manage.py zitadel_seed exited {rc} or printed no rotated browser secret"
            )
        env["ZITADEL_CLIENT_SECRET"] = secret
        ids = steps.run("the project's ids", PROJECT_IDS)
        env["ZITADEL_CLIENT_ID"], env["ZITADEL_MCP_AUDIENCE"] = ids["client_id"], ids["project"]
        yield world
    finally:
        stop(world.server)
        stop(world.worker)
        if world.realms:
            (work / "realms").write_text("\n".join(world.realms))
            subprocess.run(
                [pybin, "-c", PROLOGUE + REMOVE_REALMS, str(work / "realms")],
                cwd=ROOT,
                capture_output=True,
                env=env,
            )
        if world.mail_ids:
            body = json.dumps({"IDs": sorted(set(world.mail_ids))}).encode()
            try:
                mailpit("/api/v1/messages", "DELETE", body)
            except OSError:
                pass
        if made:
            db("db_drop", env["DATABASE_NAME"], env=env)


@dataclass
class Killed:
    """What the kill drill saw: after the kill, after the resume, and the platform at the end."""

    org: str
    after_kill: dict[str, str]
    resumed: dict[str, str]
    final: dict[str, str]


@pytest.fixture(scope="module")
def killed(live: Live) -> Killed:
    """Tenant A created with the worker up, SIGKILLed on the marker, a new worker started."""
    live.start_worker()
    assert live.worker is not None
    project = live.env["ZITADEL_PROJECT_NAME"]
    watch = live.work / "watch.out"
    with watch.open("wb") as sink:
        watcher = subprocess.Popen(
            [
                live.steps.pybin,
                "-c",
                WATCHER,
                str(live.worker_log),
                f'"{MARKER}"',
                f'{project} {live.slug_a}"',
                str(live.worker.pid),
            ],
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    live.create_tenant(live.slug_a)
    watcher.wait()
    said = dict(line.split("=", 1) for line in watch.read_text().splitlines() if "=" in line)
    if not said.get("killed"):
        raise CouldNotLook(
            f"the worker's log carried no {MARKER} line for {live.slug_a} in 180 s;"
            " no moment to kill at"
        )
    live.worker.wait()
    live.worker = None
    after = live.realm_state(live.slug_a)
    if after["org"]:
        live.realms.append(after["org"])
    if after["org"] and after["grant"]:
        raise CouldNotLook(
            f"the kill landed AFTER the grant (realm {after['org']} is granted {after['grant']})"
        )
    live.start_worker()
    resumed = live.wait_home(live.slug_a, 240)
    return Killed(after["org"], after, resumed, live.realm_state(live.slug_a))


@pytest.fixture(scope="module")
def homed_b(killed: Killed, live: Live) -> dict[str, str]:
    """Tenant B created through the service road and waited for."""
    live.create_tenant(live.slug_b)
    homed = live.wait_home(live.slug_b, 120)
    org = live.realm_state(live.slug_b)["org"]
    if org:
        live.realms.append(org)
    return homed


@pytest.fixture(scope="module")
def server(live: Live) -> Live:
    """The module's server, up once the sign-in road begins."""
    if live.server is None:
        live.start_server()
    return live


@pytest.fixture(scope="module")
def invited(killed: Killed, server: Live) -> tuple[str, str]:
    """The customer invited into tenant A; the mail's text and its credential link."""
    server.invite_customer()
    text, links = server.latest_mail(1)
    return text, next((link for link in links if "userID=" in link), "")


@dataclass
class SignedIn:
    """The first sign-in: the form's answer, the API read with its session, and the join rows."""

    status: str
    location: str
    session: str
    api_status: str
    rows: dict[str, str]


@pytest.fixture(scope="module")
def signed_in(invited: tuple[str, str], server: Live) -> SignedIn:
    """The credential link's own form, on the customer host, with a fresh password."""
    link = invited[1]
    if not link:
        raise CouldNotLook(
            "the invitation carried no credential link, so there is no first sign-in"
        )
    server.password = f"{os.urandom(12).hex()}aA1!"
    server.browse("GET", link)
    if server.status != "200":
        raise CouldNotLook(
            f"the credential link answered {server.status} on {CUSTOMER_HOST}, not its form"
        )
    server.post_form(link, CUSTOMER_HOST, "action=invite", f"password={server.password}")
    status, location, session = (
        server.status,
        server.location,
        server.cookie(CUSTOMER_HOST, "sessionid"),
    )
    server.browse("GET", f"http://{CUSTOMER_HOST}:{server.port}/api/v1/widgets/")
    return SignedIn(status, location, session, server.status, server.join_rows())


def audit(live: Live) -> tuple[int, str, str]:
    """`zitadel_audit` beside the tenant count the database holds."""
    tenants = live.steps.run(
        "the tenant count",
        "from apps.core.models import Tenant\nprint(f'tenants={Tenant.objects.count()}')\n",
    )["tenants"]
    rc, text = live.steps.manage("audit", "zitadel_audit")
    return rc, text, tenants


def drifts(text: str) -> list[str]:
    """Every line of an audit that starts `DRIFT`."""
    return [line for line in text.splitlines() if line.startswith("DRIFT")]


def mode_a(live: Live, host: str) -> tuple[str, str, str]:
    """The platform's round trip started at `host`: the callback's host, its answer, the session."""
    live.jar.unlink(missing_ok=True)
    start = f"http://{host}:{live.port}/accounts/oidc/zitadel/login/"
    live.browse("GET", start)
    live.post_form(start, host)
    assert live.status == "302", f"the start answered {live.status}"
    live.browse("GET", live.location)
    assert "authRequest=" in live.location, (
        f"the authorize answered {live.status} to {live.location!r}"
    )
    page = live.location
    live.browse("GET", page)
    if live.status == "301":
        page = live.location
        live.browse("GET", page)
    assert live.status == "200", f"our page with the auth request answered {live.status}"
    live.post_form(
        page,
        host_of(page),
        "action=password",
        f"email={live.customer}",
        f"password={live.password}",
    )
    assert "/accounts/oidc/zitadel/login/callback/" in live.location and "code=" in live.location, (
        f"the password answered {live.status} to {live.location!r}, not the callback with a code"
    )
    callback_host = host_of(live.location)
    live.browse("GET", live.location)
    return callback_host, f"{live.status} {live.location}", live.cookie(host, "sessionid")


def test_a_worker_that_dies_before_it_polls_names_its_own_cause(scratch: Path) -> None:
    plant = scratch / "python"
    plant.write_text(
        "#!/usr/bin/env bash\n"
        'echo \'{"event": "workflows.worker.starting", "level": "info"}\'\n'
        "echo 'Traceback (most recent call last):'\n"
        "echo '  File \"<frozen runpy>\", line 198, in _run_module_as_main'\n"
        "echo 'RuntimeError: Failed client connect: planted, no Temporal at the planted address'\n"
        "exit 1\n"
    )
    plant.chmod(0o755)
    with pytest.raises(CouldNotLook) as refused:
        start_worker(str(plant), dict(os.environ), scratch / "dead-worker.log")
    said = str(refused.value)
    assert "no worker:" in said and "RuntimeError: Failed client connect: planted" in said, said
    assert "Traceback" not in said, said


def test_a_step_that_raises_names_itself_before_its_traceback(scratch: Path) -> None:
    python3 = shutil.which("python3")
    if python3 is None:
        raise CouldNotLook("no python3 on PATH — the planted step runs under it")
    (scratch / "django").mkdir()
    (scratch / "django" / "__init__.py").write_text("def setup():\n    pass\n")
    steps = Steps(python3, {**os.environ, "PYTHONPATH": str(scratch)}, scratch)
    with pytest.raises(CouldNotLook) as refused:
        steps.run("a planted step", 'raise RuntimeError("planted, the step\'s own exception")\n')
    first = next(line for line in steps.last_err.read_text().splitlines() if line.strip())
    assert first == "!! RuntimeError: planted, the step's own exception"
    assert (
        str(refused.value)
        == "the step 'a planted step' exited 1 — RuntimeError: planted, the step's own exception"
    )


def test_a_worker_killed_between_the_realm_and_its_grant_resumes_to_one_org(killed: Killed) -> None:
    after = killed.after_kill
    assert killed.org and not after["grant"] and after["state"] == "pending", after
    assert killed.resumed["state"] == "own_org", killed.resumed
    final = killed.final
    assert final["orgs_named"] == "1" and final["org"] == killed.org and final["grant"], final


def test_two_tenants_through_the_service_road_are_both_homed(
    homed_b: dict[str, str], live: Live
) -> None:
    assert homed_b["state"] == "own_org", homed_b
    for slug in (live.slug_a, live.slug_b):
        realm = live.realm_state(slug)
        assert realm["org"] and realm["grant"] and realm["orgs_named"] == "1", (slug, realm)


def test_zitadel_audit_agrees_with_no_drift_line(homed_b: dict[str, str], live: Live) -> None:
    rc, text, tenants = audit(live)
    assert rc == 0 and f"{tenants} of {tenants} tenants homed" in text, text
    assert not drifts(text), drifts(text)
    assert tenants == "2" and "2 of 2 tenants homed" in text, text


def test_the_customers_invitation_carries_the_customer_host(invited: tuple[str, str]) -> None:
    text, link = invited
    assert link and host_of(link) == CUSTOMER_HOST, text


def test_the_platforms_authorize_is_unconfined_by_design_at_each_host(server: Live) -> None:
    for host in (STAFF_HOST, CUSTOMER_HOST):
        start = f"http://{host}:{server.port}/accounts/oidc/zitadel/login/"
        server.browse("GET", start)
        server.post_form(start, host)
        query = parse_qs(urlsplit(server.location).query)
        scope, redirect = query.get("scope", [""])[0], query.get("redirect_uri", [""])[0]
        assert server.status == "302" and "/oauth/v2/authorize?" in server.location, (
            server.status,
            server.location,
        )
        assert host_of(redirect) == host, redirect
        assert "urn:zitadel:iam:org:id:" not in scope, scope


def test_the_customers_first_sign_in_lands_on_the_customer_host_with_the_join_in_tenant_a(
    signed_in: SignedIn,
) -> None:
    assert signed_in.status == "302" and signed_in.session, (signed_in.status, signed_in.location)
    assert signed_in.api_status == "200", signed_in.api_status
    assert signed_in.rows["in_a"] == "1" and signed_in.rows["rows"] == "1", signed_in.rows["_out"]


def test_the_platforms_round_trip_lands_a_session_on_the_host_it_started_at(
    signed_in: SignedIn, server: Live
) -> None:
    for host in (CUSTOMER_HOST, STAFF_HOST):
        callback_host, landed, session = mode_a(server, host)
        assert callback_host == host and session, (
            host,
            callback_host,
            landed,
            server.body()[-2000:],
        )
    rows = server.join_rows()
    assert rows["in_a"] == "1" and rows["rows"] == "1", rows["_out"]


def test_a_second_invitation_renders_the_sign_in_link_on_the_customer_host(
    signed_in: SignedIn, server: Live
) -> None:
    server.invite_customer()
    text, links = server.latest_mail(2)
    assert links and host_of(links[0]) == CUSTOMER_HOST, text
    assert not any("userID=" in link for link in links), text
    assert "You already sign in here" in text, text


def test_a_rollback_round_trip_keeps_the_realm_and_the_next_sign_in(
    signed_in: SignedIn, server: Live
) -> None:
    stop(server.server)
    stop(server.worker)
    server.server = server.worker = None
    before = server.join_rows()["realm_a"]
    server.steps.must("roll back", "migrate", "accounts", "0010", "--no-input")
    server.steps.must("roll forward", "migrate", "--no-input")
    rows = server.join_rows()["_out"].splitlines()
    assert (
        before
        and f"row={before} connection=none" in rows
        and "row=staff connection=none" not in rows
    ), rows
    server.start_worker()
    server.start_server()
    rc, reconciled = server.steps.manage("reconcile", "zitadel_reconcile")
    assert rc == 0, reconciled[-3000:]
    server.jar.unlink(missing_ok=True)
    login = f"http://{CUSTOMER_HOST}:{server.port}/accounts/login/"
    server.browse("GET", login)
    server.post_form(
        login,
        CUSTOMER_HOST,
        "action=password",
        f"email={server.customer}",
        f"password={server.password}",
    )
    assert server.status == "302" and server.cookie(CUSTOMER_HOST, "sessionid"), (
        server.status,
        server.location,
    )
    after = server.join_rows()
    assert after["in_a"] == "1", after["_out"]
    rc, text, tenants = audit(server)
    assert rc == 0 and f"{tenants} of {tenants} tenants homed" in text and not drifts(text), text
