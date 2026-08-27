"""Money, as a value rather than a number.

House rule 15: **no `FloatField` on money, quantity or rate.** A float cannot
represent 0.1, so `0.1 + 0.2 != 0.3`, and an invoice total that is out by a
hundredth of a cent is a reconciliation somebody spends a day on. Decimal 19,4
with an ISO-4217 currency beside it, always.

Two pieces:

* `Money` — an immutable `Decimal` + currency pair that refuses to add euros to
  dollars. An amount without a currency is not an amount; the classic bug is
  summing a column of numbers whose rows are in three currencies, and it is
  invisible until somebody's report is wrong.
* `money_fields()` — the two columns that store one. A helper rather than a
  custom `Field` subclass on purpose: two plain columns are readable in `psql`,
  indexable, and migrate like anything else, where a composite field is a
  deconstruct method somebody has to maintain forever.

    class Invoice(TenantScopedModel):
        total_amount, total_currency = money_fields()

        @property
        def total(self) -> Money:
            return Money(self.total_amount, self.total_currency)

Rounding is the caller's: this rounds nothing implicitly, because "round to two
places" is true of dollars, false of yen, and false of a unit price with four.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import models

# 19 digits, 4 of them after the point: enough for a national budget in the
# smallest denomination, and four places so a unit price or a rate survives
# without a second convention.
MAX_DIGITS = 19
DECIMAL_PLACES = 4

# ISO 4217 is three letters. The default is a setting rather than a constant so
# a product does not have to say "USD" in fifty model definitions.
CURRENCY_LENGTH = 3
DEFAULT_CURRENCY = "USD"


class CurrencyMismatch(ValueError):
    """Raised when two amounts in different currencies are combined."""


class Money:
    """An amount and the currency it is in. Immutable, and comparable only within one.

    Written out rather than made a `dataclass` for one reason: the constructor
    has to accept a `str`, an `int` or (regrettably) a `float` and normalise it,
    while the attribute is always a `Decimal`. A dataclass ties those two
    together, and the version that satisfies a type checker is the version that
    makes every call site write `Decimal(...)` — which is where somebody
    eventually writes a float instead.
    """

    __slots__ = ("_amount", "_currency")

    _amount: Decimal
    _currency: str

    def __init__(self, amount: Decimal | int | str | float, currency: str = DEFAULT_CURRENCY):
        # `Decimal(0.1)` is 0.1000000000000000055511151231257827; going through
        # `str()` first is the documented way not to inherit a float's error.
        normalised = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        code = str(currency).upper()
        if len(code) != CURRENCY_LENGTH:
            raise ValueError(f"A currency is a three-letter ISO 4217 code; got {currency!r}.")
        object.__setattr__(self, "_amount", normalised)
        object.__setattr__(self, "_currency", code)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("Money is a value: build a new one rather than changing this.")

    @property
    def amount(self) -> Decimal:
        return self._amount

    @property
    def currency(self) -> str:
        return self._currency

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount == other.amount and self.currency == other.currency

    def __hash__(self) -> int:
        return hash((self.amount, self.currency))

    def __repr__(self) -> str:
        return f"Money({self.amount!r}, {self.currency!r})"

    def _same(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"Cannot combine {self.currency} and {other.currency}. "
                "Convert one of them first, at a rate you recorded."
            )

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: int | Decimal) -> Money:
        return Money(self.amount * Decimal(str(factor)), self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._same(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._same(other)
        return self.amount >= other.amount

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"


def money_fields(
    *,
    default_currency: str = DEFAULT_CURRENCY,
    null: bool = False,
    **kwargs: Any,
) -> tuple[models.DecimalField[Any, Any], models.CharField[Any, Any]]:
    """The two columns one `Money` lives in: `(amount, currency)`.

    Unpacked into two named fields at the model, so the column names say what
    they are (`total_amount`, `total_currency`) and a migration reads normally.
    """
    amount = models.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        null=null,
        blank=null,
        **kwargs,
    )
    currency = models.CharField(
        max_length=CURRENCY_LENGTH,
        default=default_currency,
        null=null,
        blank=null,
    )
    return amount, currency
