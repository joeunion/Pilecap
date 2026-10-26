#!/usr/bin/env python3
"""The one reader and the one writer of a deployment's env file.

THE CONTRACT is the subset `docker compose --env-file` and a shell's
`set -a; . file` agree on, and nothing wider:

    NAME=value          bare, no whitespace, no quote, no `$`
    NAME='value'        single-quoted: both readers take every byte literally
    NAME="value"        double-quoted, no `$`, no backslash, no backtick
    export NAME=...     any of the three above behind `export `
    # a comment         and blank lines, kept by `entries`, skipped by the reader

READING: whitespace around the line, the name and the value is dropped; one
leading `export ` is dropped; exactly ONE matching pair of quotes around the
value is dropped — never a greedy strip, which would quietly change a value
that genuinely begins and ends with a quote character. The LAST line for a
name wins, as it does for both readers.

WRITING: `NAME='value'`, single-quoted, always — compose runs its own `${...}`
interpolation over an env file, a bcrypt hash is `$2a$14$...`, and single
quotes make compose and the shell both take it literally. A value carrying a
single quote or a newline is REFUSED rather than escaped: no two dotenv
parsers agree on an escape, and a credential one reader takes and the other
does not is worse than one that stops the writer.

WHY ONE FILE. Six readers used to disagree about a quote — one stripped one
matching pair, one stripped every `'` and never `"`, one stripped nothing — so
`POSTGRES_PASSWORD="abc"` adopted from an existing file came back out as
`'"abc"'`: RDS's master password with two quote characters in it, which no
longer authenticates. Every Python reader and writer of the file is this
module now; the shell's own `set -a; . file` is the contract's other half, and
`quality/tests/test_envfile.py` asserts the two agree on every line shape above.

Stdlib only, and importable by PATH (`sys.path.insert(0, <deploy dir>)`): it is
loaded inside a container at the moment before anything starts
(`assert_not_published.sh`), where a dependency is a reason for the belt not to
run, and by a box's system python, which may predate `str | None`.

The command line, for the shell sites that hold no Python of their own:

    envfile.py get <file> <NAME>          # the value, or nothing (exit 0 either way)
    envfile.py set <file> <NAME> <VALUE>  # replace in place, or append
    envfile.py --check <file>             # exit 1 naming every value a reader
                                          # would take with a quote still on it
"""

# The two road markers below are one line each by their grammar
# (quality/roads.py, TEXT_MARKER_RE) and their example paths alone are most of
# the line limit, so the long-line rule is off for this file; every other line
# here fits.
# ruff: noqa: E501

from __future__ import annotations

import sys
from pathlib import Path


class Refused(ValueError):
    """A value this file's grammar cannot carry; the message names the variable."""


def _parse(raw: str) -> tuple[str, str] | None:
    """One line as (name, value) under the contract, or None for a comment,
    a blank, or a line with no `=`."""
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].strip()
    name, sep, value = line.partition("=")
    if not sep:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return name.strip(), value


def entries(path: Path | str) -> list[tuple[str, str] | str]:
    """Every line in order: `(name, value)` for an assignment, the raw text for
    a comment, a blank or anything else — so a file regenerated from a manifest
    reads like the manifest it came from."""
    out: list[tuple[str, str] | str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        parsed = _parse(raw)
        out.append(parsed if parsed is not None else raw.rstrip("\n"))
    return out


# road: env_file_reader — reads a deploy env file as compose and set -a do · example: quality/tests/test_envfile.py::test_the_reader_and_the_shell_agree_on_every_line_shape
def read_env_file(path: Path | str) -> dict[str, str]:
    """NAME -> value, the last line for a name winning."""
    values: dict[str, str] = {}
    for item in entries(path):
        if isinstance(item, tuple):
            values[item[0]] = item[1]
    return values


def line(name: str, value: str) -> str:
    """`NAME='value'` — the one encoding both readers take literally."""
    if "'" in value:
        raise Refused(
            f"{name} contains a single quote. An env file is read by docker "
            "compose's dotenv parser and by a shell, and they do not agree on how "
            "to escape one. Generate or choose a value without it."
        )
    if "\n" in value:
        raise Refused(f"{name} contains a newline; an env file cannot carry one")
    return f"{name}='{value}'"


# road: env_file_writer — writes one line single-quoted, in place or appended · example: quality/tests/test_envfile.py::test_the_adopt_path_round_trips_a_double_quoted_password
def set_key(path: Path | str, name: str, value: str) -> None:
    """Write `name` as `line(name, value)`: every existing line for the name is
    replaced where it stands (nothing is reordered), or one line is appended.
    The file keeps its inode, so its owner, group and mode are untouched."""
    path = Path(path)
    new = line(name, value)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replaced = False
    for index, raw in enumerate(lines):
        parsed = _parse(raw)
        if parsed is not None and parsed[0] == name:
            lines[index] = new
            replaced = True
    if not replaced:
        lines.append(new)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check(path: Path | str) -> list[str]:
    """The names whose value, as read, still begins and ends with a quote —
    a value an older writer re-wrapped (`'"abc"'`), which no reader unwraps."""
    return sorted(
        name
        for name, value in read_env_file(path).items()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"')
    )


def _main(argv: list[str]) -> int:
    usage = "usage: envfile.py get <file> <NAME> | set <file> <NAME> <VALUE> | --check <file>"
    if len(argv) == 3 and argv[0] == "get":
        path = Path(argv[1])
        if path.exists():
            value = read_env_file(path).get(argv[2])
            if value is not None:
                print(value)
        return 0
    if len(argv) == 4 and argv[0] == "set":
        try:
            set_key(argv[1], argv[2], argv[3])
        except Refused as error:
            print(f"!! envfile: {error}", file=sys.stderr)
            return 2
        return 0
    if len(argv) == 2 and argv[0] == "--check":
        path = Path(argv[1])
        if not path.is_file():
            print(f"!! envfile: no such env file: {path}", file=sys.stderr)
            return 2
        wrapped = check(path)
        for name in wrapped:
            print(
                f"!! envfile: {name} reads with a quote still on it — an older writer "
                "re-wrapped it; restore it from the vault"
            )
        return 1 if wrapped else 0
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
