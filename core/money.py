"""Money in Rookwise: USD as `decimal.Decimal`, never float.

Amounts are whole micro-USD (USD 0.000001). The ledger rounds each amount once, when it
enters (`to_micro_usd`), so every sum after that is exact; the rounding rules live in
`rookwise.ledger`.

In pydantic models (the contracts in `rookwise.schemas`, the API in
`rookwise.api.models`, harness records), money is the `Usd` type: a `Decimal` in
Python and a decimal string with exactly six decimals in JSON, for example
`"0.002350"`. A float is refused everywhere: `require_decimal` raises TypeError, and
the `Usd` validator raises a validation error. Amounts with more precision than a
micro-USD are refused by the validator rather than rounded, so a model never changes a
value it is given.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import PlainSerializer, PlainValidator, WithJsonSchema

MICRO_USD = Decimal("0.000001")
ZERO_USD = Decimal("0.000000")
USD_PATTERN = r"^[0-9]+\.[0-9]{6}$"
_USD_TEXT = re.compile(USD_PATTERN)


def require_decimal(value: object, name: str) -> Decimal:
    """`value` itself when it is a finite, non-negative Decimal. A float, or any other
    type, raises TypeError: this is the guard that keeps floats out of the ledger."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a decimal.Decimal, not {type(value).__name__}")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative amount, not {value}")
    return value


def to_micro_usd(value: Decimal, rounding: str) -> Decimal:
    """`value` rounded to whole micro-USD with a `decimal` rounding mode."""
    return value.quantize(MICRO_USD, rounding=rounding)


def format_usd(value: Decimal) -> str:
    """The JSON form: six decimals, no exponent (`Decimal("0.0048")` -> `"0.004800"`)."""
    return format(value.quantize(MICRO_USD), "f")


def _parse(value: Any, positive: bool) -> Decimal:
    if isinstance(value, str):
        if not _USD_TEXT.fullmatch(value):
            raise ValueError(
                f'a USD amount is a string with six decimals, such as "0.002350", not {value!r}'
            )
        amount = Decimal(value)
    elif isinstance(value, Decimal):
        if not value.is_finite() or value < 0:
            raise ValueError(f"a USD amount must be finite and non-negative, not {value}")
        try:
            amount = value.quantize(MICRO_USD)
        except InvalidOperation:
            raise ValueError(f"{value} is too large for a USD amount") from None
        if amount != value:
            raise ValueError(f"{value} has more precision than a micro-USD")
    else:
        raise ValueError(
            'a USD amount is a decimal string such as "0.002350" or a Decimal, '
            f"not {type(value).__name__}"
        )
    if positive and amount <= 0:
        raise ValueError("this USD amount must be greater than zero")
    return amount


def _usd_type(positive: bool) -> Any:
    description = 'USD as a decimal string with exactly six decimals (micro-USD), e.g. "0.002350"'
    if positive:
        description += "; greater than zero"
    return Annotated[
        Decimal,
        PlainValidator(lambda value: _parse(value, positive)),
        PlainSerializer(format_usd, return_type=str, when_used="json"),
        WithJsonSchema({"type": "string", "pattern": USD_PATTERN, "description": description}),
    ]


Usd = _usd_type(positive=False)
PositiveUsd = _usd_type(positive=True)
