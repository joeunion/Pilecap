# Changelog

What changed in **the template's system layer** — the part a product inherits
and, one day, wants to pull again.

There is deliberately **no sync tooling yet** (`architecture.md`): a product
cherry-picks the system-layer commits it wants, and this file plus
`TEMPLATE_VERSION` is how it knows which ones exist and what they cost. The
trigger for building `scripts/template_sync.sh` is three products existing.

So an entry here answers one question — *would somebody who cloned this last
month want to pull this, and what would it change under them?* — and nothing
else. No counts of anything, no status: those go stale without this file
changing, which is the failure mode `CLAUDE.md` names.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html), where a
**major** is a change a product cannot take without editing its own code, a
**minor** adds something a product can ignore, and a **patch** fixes something
that was already meant to work.

## [Unreleased]

## [1.0.0] — Initial release

[Unreleased]: https://github.com/
[1.0.0]: https://github.com/
