# rule-16: one worked customer portal — the example's second face, not a collection of them
# golden: portal begin
from typing import ClassVar

from django.apps import AppConfig


class ExamplePortalConfig(AppConfig):
    """The worked customer face: a second audience on the example's records.

    **What a product copies from here is the SHAPE of a second surface.** One
    product, two hosts: staff at one, customers at the other, one database and
    one set of services. This app owns everything the customer surface adds —
    the surface's declaration (`surfaces.py`), the role it admits (`roles.py`)
    and the one noun customers write, a `PortalRequest` about a widget — and
    nothing of the staff noun it faces: `Widget` stays `apps.example`'s, read
    here through its own selector and never through its model.

    **The split is two teams.** One owns `apps/example` and the staff face; the
    other owns this app and the customer folder pair
    (`frontend/src/screens/customer/`, `frontend/src/app/(customer)/`). The one
    line they share is `SURFACE_HOSTS` in the environment.

    `depends_on`:

    * `core` — the scoped managers, `@service`, the authorization vocabulary,
      the surface declaration;
    * `accounts` — `requester` is a person from that app;
    * `events` — every submission says what happened, inside its transaction;
    * `example` — the one sideways arrow: a request names a `Widget`, read
      through `apps.example.selectors.get_widget`.
    """

    name = "apps.example_portal"
    verbose_name = "Example portal"
    depends_on: tuple[str, ...] = ("core", "accounts", "events", "example")
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 11,
        "91.docstring-tail": 89,
        "91.module-tail": 84,
    }


# golden: portal end
