# road: belt — an executable that is not running under bash refuses at its first line, exit 2 · example: quality/tests/test_refusal_seam.py::test_every_executable_refuses_sh_and_zsh_at_its_first_line
#
# THE BELT: one line at the top of every executable under `scripts/`,
#
#     . "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
#
# and this file is what it sources. It is POSIX on purpose — `sh`, `dash`,
# `zsh` and bash in POSIX mode all have to be able to READ it, because those
# are exactly the shells it exists to turn away — and an `exit` in a sourced
# file exits the shell that sourced it, which is the whole mechanism.
#
# WHY. The executables here are bash — not POSIX sh, and not zsh. The shebang
# is honoured by `./this`; `sh this` and `zsh this` IGNORE it, and neither of
# them fails where the mistake was made. Measured on this tree:
#
#   zsh scripts/queue_cited.sh   exit 2 blaming the TREE ("this is not a
#                                checkout root") for zsh's word-splitting
#   zsh scripts/kill_mine.sh     an ordinary-looking census of nothing
#   sh  scripts/sweep.sh         "lifecycle.sh: line 152: syntax error"
#
# A wrong shell here does not crash. It ANSWERS, and the answer looks like the
# tree's fault.
#
# TWO TESTS, because on macOS `/bin/sh` IS bash: BASH_VERSION is set under
# `sh x.sh` and only POSIX MODE tells the two apart (SHELLOPTS carries
# `posix`). On Linux `/bin/sh` is dash and the first test is the one that
# fires. Neither test alone covers both machines.
#
# THE PATH IN THE BELT LINE. `${BASH_SOURCE:-$0}` is POSIX syntax — an
# unsubscripted name, which dash and zsh read as an unset variable and bash
# reads as element 0 of its array — so it parses everywhere. Under bash it is
# the file being run OR SOURCED (a drive that sources `rung_start.sh` for one
# function still finds this file beside it); under the wrong shell it falls back
# to `$0`, the script's own path. The run from `/` is in the drive.
#
# WHOSE NAME THE SENTENCE PRINTS. `$0` inside a sourced file is the CALLER's
# under sh, dash and bash, and this file's own under zsh — so zsh is asked for
# the script it was started on (`ZSH_ARGZERO`), and the sentence is the one the
# caller used to print itself, byte for byte.
#
# A SOURCED LIBRARY must never carry the belt. There the interpreter is the
# caller's ON PURPOSE and the exit would kill the caller's shell — the argument
# is scripts/db.sh's, at the head of its sourced-library contract, and it is why
# db.sh is the one executable in this tree deliberately without one.
#
# EXIT: returns 0 under bash outside POSIX mode; otherwise prints the one
# sentence on stderr and exits 2 — the caller's shell, not just this file.

bash_only__self=${ZSH_ARGZERO:-$0}
if [ -z "${BASH_VERSION:-}" ]; then
    echo "${bash_only__self##*/}: must run under bash — not sh, not zsh. Try \`bash ${bash_only__self}\`." >&2
    exit 2
fi
case ":${SHELLOPTS:-}:" in
*:posix:*)
    echo "${bash_only__self##*/}: bash is in POSIX mode — which is what \`sh ${bash_only__self}\` does on a" >&2
    echo "  machine whose /bin/sh is bash. Try \`bash ${bash_only__self}\`." >&2
    exit 2
    ;;
esac
unset bash_only__self
