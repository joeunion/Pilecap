# census: cross-app population=config/**/*.py,.env.example every environment read under config/
"""Every variable `config/` reads from the environment has a line in `.env.example`.

`config/settings/base.py`'s docstring promises `.env.example` is "the complete
list of variables this module reads". This holds it, over the whole of
`config/` rather than one module: every `env.<kind>("NAME", …)` and every
named `os.environ` read is a member, and each must appear in `.env.example` as
`NAME=…` or, for a knob a clone leaves unset on purpose, `# NAME=…`.

And settings read the environment through `env` — the reader that honours
`.env` — except where `BYPASSES` names the read and says why.

Blind spots, declared: a read outside `config/` (a management command, an app
module) is not this population; a read whose name is not a string literal
(`env.str(name)`) is not seen; the census reads names, never values.
"""

from __future__ import annotations

import ast
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.core.tests.tree_census import source_text, source_tree

BASE_DIR = Path(settings.BASE_DIR)

#: A declaration in `.env.example`: `NAME=` live, or `# NAME=` left unset.
DECLARED = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)

#: The `os.environ` reads under `config/settings/` that do not go through
#: `env`, each with the reason it cannot. A new one is a finding until listed.
BYPASSES: dict[str, str] = {
    "ANYMAIL_*": (
        "a read by PREFIX, not by name — every `ANYMAIL_<KEY>` the deployment "
        "sets becomes one Anymail option; `env` reads one name at a time"
    ),
}


@dataclass(frozen=True)
class Read:
    """One environment read: where it is, the name it reads, and whether it bypasses `env`."""

    path: str
    line: int
    name: str
    through_env: bool


def _string(node: ast.AST) -> str | None:
    """The literal a node spells, if it is a string literal."""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _is_os_environ(node: ast.AST) -> bool:
    """`os.environ`, spelled as an attribute of `os`."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def reads_in(path: Path, root: Path) -> list[Read]:
    """Every environment read one module makes, by name, in source order."""
    tree = source_tree(path)
    where = str(path.relative_to(root))
    found: list[Read] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = _string(node.args[0]) if node.args else None
            # env("NAME") and env.<kind>("NAME", ...)
            if (isinstance(func, ast.Name) and func.id == "env") or (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "env"
                and func.attr != "read_env"
            ):
                if name:
                    found.append(Read(where, node.lineno, name, through_env=True))
            # os.environ.get / setdefault / pop ("NAME"), os.getenv("NAME")
            elif isinstance(func, ast.Attribute) and (
                (_is_os_environ(func.value) and func.attr in {"get", "setdefault", "pop"})
                or (
                    func.attr == "getenv"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                )
            ):
                if name:
                    found.append(Read(where, node.lineno, name, through_env=False))
            # os.environ.items() and friends: a read by pattern
            elif (
                isinstance(func, ast.Attribute)
                and _is_os_environ(func.value)
                and func.attr in {"items", "keys", "values"}
            ):
                found.append(Read(where, node.lineno, "*", through_env=False))
        elif isinstance(node, ast.Subscript) and _is_os_environ(node.value):
            name = _string(node.slice)
            if name:
                found.append(Read(where, node.lineno, name, through_env=False))
    return found


def census(root: Path) -> list[Read]:
    """Every environment read under `root/config/`, ordered by file and line."""
    reads: list[Read] = []
    for path in sorted((root / "config").rglob("*.py")):
        reads.extend(reads_in(path, root))
    return sorted(reads, key=lambda read: (read.path, read.line))


def declared(root: Path) -> set[str]:
    """Every name `.env.example` declares, live or commented."""
    return set(DECLARED.findall(source_text(root / ".env.example")))


def undeclared(root: Path) -> list[Read]:
    """The named reads `.env.example` has no line for."""
    names = declared(root)
    return [read for read in census(root) if read.name != "*" and read.name not in names]


def unlisted_bypasses(root: Path) -> list[Read]:
    """The `config/settings/` reads that skip `env` and that `BYPASSES` does not name."""
    listed = set(BYPASSES)
    return [
        read
        for read in census(root)
        if read.path.startswith("config/settings/")
        and not read.through_env
        and read.name not in listed
        and not (read.name == "*" and any(key.endswith("*") for key in listed))
    ]


def test_the_census_reads_a_population() -> None:
    """A census that found nothing looked nowhere: the population is not empty."""
    reads = census(BASE_DIR)
    assert any(read.through_env for read in reads), "no env.<kind>( read under config/"
    assert any(not read.through_env for read in reads), "no os.environ read under config/"


def test_every_environment_read_under_config_is_declared_in_env_example() -> None:
    """A variable `config/` reads and `.env.example` does not name: a clone never learns of it."""
    missing = undeclared(BASE_DIR)
    assert not missing, "read under config/ but not in .env.example:\n" + "\n".join(
        f"  {read.path}:{read.line} {read.name}" for read in missing
    )


def test_settings_read_the_environment_through_env() -> None:
    """`env` honours `.env`; a bare `os.environ` read in settings does not, unless listed."""
    bypassing = unlisted_bypasses(BASE_DIR)
    assert not bypassing, "os.environ read in config/settings/ outside BYPASSES:\n" + "\n".join(
        f"  {read.path}:{read.line} {read.name}" for read in bypassing
    )


def test_a_planted_read_is_named(tmp_path: Path) -> None:
    """The negative: a copy of `config/` with one undeclared read is a finding that names it."""
    shutil.copytree(BASE_DIR / "config", tmp_path / "config")
    shutil.copy(BASE_DIR / ".env.example", tmp_path / ".env.example")
    base = tmp_path / "config" / "settings" / "base.py"
    base.write_text(
        source_text(base) + '\nZZZ_PROBE: str = env.str("ZZZ_PROBE", default="")\n',
        encoding="utf-8",
    )
    assert [read.name for read in undeclared(tmp_path)] == ["ZZZ_PROBE"]

    base.write_text(
        source_text(base) + '\nZZZ_RAW = os.environ.get("ZZZ_RAW", "")\n',
        encoding="utf-8",
    )
    assert "ZZZ_RAW" in [read.name for read in unlisted_bypasses(tmp_path)]
