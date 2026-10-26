"""`manage.py declare <namespace>` — a product's day-zero declaration, once, from the tree."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings
from django.core.management.base import CommandError

from apps.core.management import BaseCommand

DRAWER = "quality/local/rules.yaml"
BASE = "scripts/local/template-base"
REMOTE = "template"
SHAPE = "DJB_IDENTITY_SHAPE=platform_apps=own"  # pragma: allowlist secret
NEXT = f"next: git add {DRAWER} {BASE} && git commit"


def _refuse(message: str) -> CommandError:
    """A refusal that exits 2, before anything is written."""
    return CommandError(message, returncode=2)


def _git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """`git <argv>` in `root`, never raising."""
    return subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=False)  # noqa: S603, S607 — argv list to `git` from PATH in the developer's checkout; no shell


def template_ids_through() -> int:
    """The highest integer rule id the template on this tree has minted."""
    from quality.engine.world import RULES, is_template_id

    return max(int(r["id"]) for r in RULES if is_template_id(str(r["id"])))


def refuse_namespace(namespace: str) -> None:
    """Refuse a namespace the engine would refuse, naming its grammar."""
    from quality.engine.world import NAMESPACE_RE, TEMPLATE_CHECK_PREFIX

    if not NAMESPACE_RE.match(namespace):
        raise _refuse(
            f"{namespace!r} is not a namespace: one lowercase word matching "
            f"{NAMESPACE_RE.pattern}, because it is spelled in a rule id, a directory name, "
            "a valve and a check tag (docs/sdk/day-zero.md)."
        )
    if namespace == TEMPLATE_CHECK_PREFIX:
        raise _refuse(
            f"{namespace!r} is the template's own namespace; pick your product's word "
            "(docs/sdk/day-zero.md)."
        )


def head_commit(root: Path) -> str:
    """The commit at HEAD, refused when there is none."""
    from quality.could_not_look import tool_said

    done = _git(root, "rev-parse", "HEAD")
    if done.returncode != 0:
        raise _refuse(
            f"{root} has no commit at HEAD — declare runs in a clone of the template."
            f"{tool_said(done.stderr)}"
        )
    return done.stdout.strip()


def release_base(root: Path) -> tuple[str | None, str]:
    """(the template release this clone stands on, or None, and how it was found)."""
    if _git(root, "remote", "get-url", REMOTE).returncode != 0:
        return None, f"no `{REMOTE}` remote to read a release from"
    tag = f"v{(root / 'TEMPLATE_VERSION').read_text().strip()}"
    base = _git(root, "merge-base", "HEAD", f"refs/tags/{tag}")
    if base.returncode != 0:
        return None, f"{tag} does not resolve — `git fetch {REMOTE} --tags`, then declare again"
    return base.stdout.strip(), f"git merge-base HEAD {tag}"


def product_apps(root: Path) -> list[str]:
    """The apps under `apps/` that are not the platform's."""
    loaded = yaml.safe_load((root / "quality/partition.yaml").read_text()) or {}
    platform = set(loaded.get("platform_apps") or [])
    return sorted(
        p.parent.name for p in (root / "apps").glob("*/apps.py") if p.parent.name not in platform
    )


class Command(BaseCommand):
    help = "Declare this clone a product: its rule-id namespace, its template base, its shape."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("namespace", help="Your product's one lowercase word, e.g. `acme`.")
        parser.add_argument(
            "--root",
            default=None,
            help="The checkout to declare. Defaults to <BASE_DIR>; a temp directory is for tests.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        namespace = str(options["namespace"]).strip()
        root = Path(options["root"] or settings.BASE_DIR)
        refuse_namespace(namespace)
        changed = [
            self.drawer(root, namespace),
            self.shape(root),
            self.base(root),
            self.env(root),
        ]
        if not any(changed):
            self.stdout.write(f"declared as {namespace!r} already — nothing changed.")
        pending = _git(root, "status", "--porcelain", "--", DRAWER, BASE).stdout.strip()
        if pending:
            self.stdout.write(NEXT)

    def drawer(self, root: Path, namespace: str) -> bool:
        """Write the two namespace keys into the drawer, keeping what it already holds."""
        path = root / DRAWER
        text = path.read_text() if path.is_file() else ""
        loaded = yaml.safe_load(text) if text else {}
        held = loaded if isinstance(loaded, dict) else {}
        have = held.get("rule_id_namespace")
        if have is not None and str(have) != namespace:
            raise _refuse(
                f"{DRAWER} already declares rule_id_namespace: {have} — a product declares its "
                "namespace once; nothing was written."
            )
        through = template_ids_through()
        recorded = held.get("template_rule_ids_through")
        if have is not None and recorded is not None:
            if str(recorded) == str(through):
                self.stdout.write(
                    f"{DRAWER}: rule_id_namespace: {have}, template_rule_ids_through: {through} "
                    "(kept)"
                )
                return False
            path.write_text(
                re.sub(
                    r"^template_rule_ids_through:.*$",
                    f"template_rule_ids_through: {through}",
                    text,
                    count=1,
                    flags=re.M,
                )
            )
            self.stdout.write(f"{DRAWER}: template_rule_ids_through: {recorded} → {through}")
            return True
        head = "" if have is not None else f"rule_id_namespace: {namespace}\n"
        if held.get("template_rule_ids_through") is None:
            head += f"template_rule_ids_through: {through}\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(head + text)
        self.stdout.write(
            f"{DRAWER}: rule_id_namespace: {namespace}, template_rule_ids_through: {through}"
        )
        return True

    def shape(self, root: Path) -> bool:
        """Carry the identity shape into the tracked drawer once the product has an app."""
        from quality.engine.rules import identity_shape_in

        path = root / DRAWER
        text = path.read_text() if path.is_file() else ""
        held = identity_shape_in(text)
        if held is not None:
            self.stdout.write(f"{DRAWER}: identity_shape: {held} (kept)")
            return False
        env = root / ".env"
        typed = [
            ln
            for ln in (env.read_text() if env.is_file() else "").splitlines()
            if ln.startswith("DJB_IDENTITY_SHAPE=")
        ]
        value = (typed[-1] if typed else SHAPE).partition("=")[2].strip()
        if "platform_apps=own" not in value or not product_apps(root):
            return False
        line = f"identity_shape: {value}"
        if identity_shape_in(line) != value:
            line = f"identity_shape: {json.dumps(value)}"
        sep = "" if text.endswith("\n") or not text else "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{text}{sep}{line}\n")
        self.stdout.write(f"{DRAWER}: += {line}")
        return True

    def base(self, root: Path) -> bool:
        """Write the template commit this clone stands on; move it when the release moved."""
        path = root / BASE
        sha, how = release_base(root)
        if path.is_file():
            was = path.read_text().strip()
            if sha is None or sha == was:
                self.stdout.write(f"{BASE}: {was} (kept; {how})")
                return False
            path.write_text(sha + "\n")
            self.stdout.write(f"{BASE}: {was} → {sha} ({how})")
            return True
        if sha is None:
            sha, how = head_commit(root), f"HEAD; {how}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sha + "\n")
        self.stdout.write(f"{BASE}: {sha} ({how})")
        return True

    def env(self, root: Path) -> bool:
        """Append the identity shape to `.env` once the product has an app of its own."""
        path = root / ".env"
        text = path.read_text() if path.is_file() else ""
        declared = [ln for ln in text.splitlines() if ln.startswith("DJB_IDENTITY_SHAPE=")]
        if declared and "platform_apps=own" in declared[-1]:
            self.stdout.write(f".env: {declared[-1]} (kept)")
            return False
        if declared:
            self.stdout.write(
                f".env: {declared[-1]} — add `platform_apps=own` to it (`;`-separated) "
                "once you have an app of your own; declare does not edit a shape you wrote."
            )
            return False
        apps = product_apps(root)
        if not apps or not path.is_file():
            when = "./scripts/setup.sh writes .env first" if apps else "after your first newapp"
            self.stdout.write(
                f".env: not yet — {SHAPE} is added when you run declare again {when} "
                "(the template's own app census skips once you have an app outside it)."
            )
            return False
        sep = "" if text.endswith("\n") or not text else "\n"
        path.write_text(f"{text}{sep}{SHAPE}\n")
        self.stdout.write(f".env: += {SHAPE} (your apps: {', '.join(apps)})")
        return True
