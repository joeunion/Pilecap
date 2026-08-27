

# The two wraps this module really holds, in the shape it really holds them.
# Both names are in the census with their reasons, and both are still defined on
# the installed django-ninja, so this must stay silent: the rule refuses an
# UNDECLARED private and a censused one that has gone, never the act of holding
# a seam a library did not publish. `config/api.py` holds three attribute names
# on purpose and says so out loud in two ADRs.
def _guard_the_ceiling_again(operation: object) -> None:
    inner = getattr(operation, "_run_checks", None)
    if inner is None:
        raise RuntimeError("this ninja Operation has no `_run_checks`")

    def run_checks(request: object) -> object:
        return inner(request)

    operation._run_checks = run_checks  # type: ignore[attr-defined]


def _speak_the_method_refusal_again(path_view: object) -> None:
    inner_sync = getattr(path_view, "_sync_view", None)
    inner_async = getattr(path_view, "_async_view", None)
    if inner_sync is None or inner_async is None:
        raise RuntimeError("this ninja PathView has no `_sync_view`/`_async_view`")

    def sync_view(request: object) -> object:
        return inner_sync(request)

    async def async_view(request: object) -> object:
        return await inner_async(request)

    path_view._sync_view = sync_view  # type: ignore[attr-defined]
    path_view._async_view = async_view  # type: ignore[attr-defined]
