"""The demanded shape: a resource, and the wall that has to arrive with it.

The rule is not "no resources". It is "no registration on a surface nobody
walled", and the way to satisfy it is the way `apps/core/mcp.py` satisfies it for
tools: the app that opens the surface installs the guard from its own
`register()`, so whatever the apps discovered after it contribute is covered
without this module knowing they exist.

That the guard is CORRECT is not this rule's claim and is said so in
`does_not_cover` — the wall tests own that. What the rule can see, and what this
proves it does not refuse, is a surface somebody walled.
"""

from typing import Any


def install_resource_ceiling_gate(server: Any) -> None:
    """The `resources/read` twin of `install_ceiling_gate`, in outline."""
    dispatch = server.read_resource

    async def read_resource_within_ceiling(uri: Any, context: Any = None) -> Any:
        return await dispatch(uri, context)

    server.read_resource = read_resource_within_ceiling


def register(server: Any) -> None:
    @server.resource("widget://catalogue")
    def widget_catalogue() -> str:
        return "every widget this tenant can see"

    install_resource_ceiling_gate(server)
