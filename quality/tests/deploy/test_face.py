"""The face on the box: its service, its image on the one list, and the edge's one path split.

does-not-cover: whether the image boots or the face renders — a render is shape; boot is staging's.
does-not-cover: a backend root a product mounts outside `config/urls.py`, ASGI or the static prefix.
does-not-cover: which of the face's routes answer 200 — Caddy sends every non-backend path there.
does-not-cover: Caddy's own reading of the file — `caddy validate` is the proof, run by hand.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.deploy.test_compose_floor import (
    BOX_FILE,
    derive_env,
    environ,
    load,
    render,
    services,
)
from quality.tests.fixtures.scratch import require_scratch

pytestmark = pytest.mark.drives(
    "deploy/compose.yaml",
    "deploy/Caddyfile",
    "deploy/provision.sh",
    "deploy/release.sh",
    "deploy/stage.sh",
    "Dockerfile",
    "frontend/next.config.ts",
    "config/urls.py",
    "config/settings/base.py",
    "apps/core/mcp.py",
    "apps/realtime/consumers.py",
    ".github/workflows/ci.yml",
)

ROOT = Path(__file__).resolve().parents[3]
CADDYFILE = ROOT / "deploy" / "Caddyfile"
NEXT_CONFIG = ROOT / "frontend" / "next.config.ts"
CI = ROOT / ".github" / "workflows" / "ci.yml"
PROVISION = ROOT / "deploy" / "provision.sh"
FACE = "frontend"
FACE_UPSTREAM = "frontend:3000"
WEB_UPSTREAM = "web:8000"
#: The two roots `config/urls.py` mounts as fallbacks a product with a face never reaches.
FACE_SHADOWS = {"", "welcome/"}
MATCHER = re.compile(r"^\s*@backend\s+path\s+(.+)$", re.MULTILINE)
REWRITE_SOURCE = re.compile(r"source:\s*`([^`]*)`")
PREFIX_CONST = re.compile(r'const ([A-Z_]+_PREFIX) = "([^"]+)"')


def face_render(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The box file rendered by docker compose, every required slot answered with a dummy."""
    if shutil.which("docker") is None:
        raise CouldNotLook("no docker on PATH — the render is docker compose's own")
    work = require_scratch(tmp_path_factory.mktemp("face"), ROOT).resolve()
    env_file = derive_env(BOX_FILE, work / "box.env")
    rc = render([BOX_FILE], env_file, work / "box.json")
    if rc != 0:
        raise CouldNotLook(
            f"compose.yaml does not render: {Path(f'{work}/box.json.err').read_text()}"
        )
    return load(work / "box.json")


@pytest.fixture(scope="module")
def box(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The rendered box stack."""
    return face_render(tmp_path_factory)


def paths_for(route: str) -> set[str]:
    """The Caddy path matchers that hand `route`'s first segment, and all beneath it, to web."""
    segment = route.strip("/").split("/")[0]
    if "/" not in route.strip("/") and not route.endswith("/"):
        return {f"/{segment}"}
    return {f"/{segment}", f"/{segment}/*"}


def constants(tree: ast.Module) -> dict[str, str]:
    """A module's top-level string constants, by name."""
    found: dict[str, str] = {}
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
        value = getattr(node, "value", None)
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
            if isinstance(value.value, str):
                found[target.id] = value.value
    return found


def literal(node: ast.expr, names: dict[str, str], where: Path) -> str:
    """A route argument spelled as a literal, a module constant or an f-string of them."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    if isinstance(node, ast.JoinedStr):
        parts = [v.value if isinstance(v, ast.FormattedValue) else v for v in node.values]
        return "".join(literal(part, names, where) for part in parts)
    raise CouldNotLook(
        f"{where.relative_to(ROOT)}: a route spelled {ast.dump(node)} is not readable"
    )


def routes_in(path: Path, attribute: str) -> list[str]:
    """The first argument of every `path(...)` in the module's `attribute` list."""
    tree = ast.parse(path.read_text())
    names = constants(tree)
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
        value = getattr(node, "value", None)
        if isinstance(target, ast.Name) and target.id == attribute and isinstance(value, ast.List):
            return [literal(call.args[0], names, path) for call in value.elts
                    if isinstance(call, ast.Call)]  # fmt: skip
    raise CouldNotLook(f"{path.relative_to(ROOT)} assigns no '{attribute}' list")


def static_url() -> str:
    """`STATIC_URL`'s default in the base settings."""
    for line in (ROOT / "config" / "settings" / "base.py").read_text().splitlines():
        if line.startswith("STATIC_URL"):
            found = re.search(r'default="([^"]+)"', line)
            if found:
                return found.group(1)
    raise CouldNotLook("config/settings/base.py spells no STATIC_URL default")


def backend_paths() -> set[str]:
    """Every root the backend answers: the root URLconf, the MCP mount, the sockets, the statics."""
    routes = set(routes_in(ROOT / "config" / "urls.py", "urlpatterns")) - FACE_SHADOWS
    for consumers in sorted((ROOT / "apps").glob("*/consumers.py")):
        routes |= set(routes_in(consumers, "websocket_urlpatterns"))
    mcp = constants(ast.parse((ROOT / "apps" / "core" / "mcp.py").read_text())).get("MCP_PATH")
    if mcp is None:
        raise CouldNotLook("apps/core/mcp.py spells no MCP_PATH")
    found: set[str] = set().union(*(paths_for(r) for r in routes))
    return found | paths_for(f"{mcp}/") | paths_for(static_url())


def caddy_backend() -> set[str]:
    """The product block's `@backend` matcher, as Caddy reads it."""
    found = MATCHER.findall(CADDYFILE.read_text())
    if len(found) != 1:
        raise CouldNotLook(
            f"deploy/Caddyfile carries {len(found)} '@backend path' matchers, not one"
        )
    return set(found[0].split())


def caddy_routes(path: str, matchers: set[str]) -> bool:
    """Whether a request for `path` meets one of `matchers` (Caddy's exact and `/*` forms)."""
    return any(path == m or (m.endswith("/*") and path.startswith(m[:-1])) for m in matchers)


def rewrite_prefixes() -> list[str]:
    """The literal prefix of every source the dev proxy hands to the backend."""
    text = NEXT_CONFIG.read_text()
    prefixes = dict(PREFIX_CONST.findall(text))
    sources = REWRITE_SOURCE.findall(text)
    if "API_PREFIX" not in prefixes or not sources:
        raise CouldNotLook(
            "frontend/next.config.ts no longer spells API_PREFIX and a rewrite source"
        )
    out = []
    for source in sources:
        for name, value in prefixes.items():
            source = source.replace("${" + name + "}", value)
        out.append(source.split(":")[0])
    return out


def test_the_face_is_a_service_on_the_box_pulled_by_the_tree_tag(box: dict[str, Any]) -> None:
    face = services(box).get(FACE) or {}
    assert face.get("image") == "compose-floor-dummy/djb-frontend:compose-floor-dummy", face
    assert "build" not in face, "the box never builds (ADR deploy-4)"
    assert "ports" not in face, "only the edge publishes a port"


def test_the_face_waits_for_a_healthy_web_and_reaches_it_by_name(box: dict[str, Any]) -> None:
    face = services(box).get(FACE) or {}
    assert (face.get("depends_on") or {}).get("web", {}).get("condition") == "service_healthy"
    assert (face.get("environment") or {}).get("DJANGO_ORIGIN") == f"http://{WEB_UPSTREAM}"
    assert face.get("healthcheck", {}).get("test"), "the face declares its own liveness"


def test_the_edge_waits_for_the_face(box: dict[str, Any]) -> None:
    assert FACE in (services(box).get("caddy", {}).get("depends_on") or {})


def test_the_edge_hands_exactly_the_backend_roots_to_web() -> None:
    assert caddy_backend() == backend_paths()


def test_every_path_the_dev_proxy_sends_to_django_the_edge_sends_to_web() -> None:
    held = caddy_backend()
    missed = [p for p in rewrite_prefixes() if not caddy_routes(p, held)]
    assert missed == [], missed


def test_everything_else_reaches_the_face() -> None:
    text = CADDYFILE.read_text()
    assert re.search(r"handle @backend \{\s*reverse_proxy " + WEB_UPSTREAM, text)
    assert re.search(r"\n\thandle \{\s*reverse_proxy " + FACE_UPSTREAM, text)
    assert not caddy_routes("/", caddy_backend()) and not caddy_routes("/welcome", caddy_backend())


def test_the_one_image_list_names_the_face() -> None:
    done = subprocess.run(
        [str(PROVISION), "image-services"], capture_output=True, text=True, env=environ()
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["web", "worker", FACE]


def test_ci_and_the_deploy_scripts_read_the_one_list() -> None:
    assert "for target in web worker" not in CI.read_text()
    # Seven: images' have/build/USER/scan steps, images-push's push/manifest/attest steps.
    assert CI.read_text().count('services="$(./deploy/provision.sh image-services)" || exit 1') == 7
    for script in ("release.sh", "stage.sh"):
        assert "image-services" in (ROOT / "deploy" / script).read_text(), script


def test_the_dockerfile_builds_the_face_as_a_target() -> None:
    text = (ROOT / "Dockerfile").read_text()
    assert re.search(r"^FROM \S+ AS frontend$", text, re.MULTILINE)
    assert 'output: "standalone"' in NEXT_CONFIG.read_text()
