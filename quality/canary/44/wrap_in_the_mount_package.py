

# Planted: a wrap held somewhere in `config/` other than `api.py`. The census is
# a property of the TREE and not of one file — the mounts are four modules and
# any of them can reach into a library's privates — so the walk has to be the
# package, and this is what proves it is.
def _hold_the_session_seam(mount: object) -> None:
    inner = getattr(mount, "_resolve_the_session", None)
    if inner is None:
        raise RuntimeError("this mount has no `_resolve_the_session`")

    def resolve_the_session(scope: object) -> object:
        return inner(scope)

    mount._resolve_the_session = resolve_the_session  # type: ignore[attr-defined]
