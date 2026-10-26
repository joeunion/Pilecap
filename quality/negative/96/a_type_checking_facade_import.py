from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pilecap.tenancy import Tenant


# Legal: a type-only import, through the facade.
def label(tenant: "Tenant") -> str:
    return str(tenant)
