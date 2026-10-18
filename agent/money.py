"""Currencies and the conversions between written amounts and minor units.

All money inside the system is a whole number of minor units (cents for
KES). Amounts written with more decimals than the currency has are rounded
down. Text is parsed with Decimal, never float.
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal, InvalidOperation

# code -> number of decimal places. Add a currency here to support it.
CURRENCIES: dict[str, int] = {
    "KES": 2,
}
DEFAULT_EXPONENT = 2

BPS_PER_WHOLE = 10_000  # 100% in basis points


class Unreadable:
    """A value that was supplied but isn't a number."""

    def __init__(self, raw: object) -> None:
        self.raw = "" if raw is None else str(raw)

    def __repr__(self) -> str:
        return f"Unreadable({self.raw!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Unreadable) and other.raw == self.raw


Number = int | float
Parsed = Number | Unreadable | None  # None means missing


def exponent(currency: str | None) -> int:
    return CURRENCIES.get(currency or "", DEFAULT_EXPONENT)


def _decimal(value: object) -> Decimal | Unreadable | None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if isinstance(value, bool):
        return Unreadable(value)
    try:
        text = str(value).strip().replace(",", "").replace("_", "")
        d = Decimal(text)
    except (InvalidOperation, ValueError):
        return Unreadable(value)
    if not d.is_finite():
        return Unreadable(value)
    return d


def _as_number(d: Decimal) -> Number:
    """Whole values become int; anything else stays a float so the rules can flag it."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def to_minor(value: object, currency: str | None) -> Parsed:
    """'15000.509' KES -> 1500050 (rounded down to the cent)."""
    d = _decimal(value)
    if not isinstance(d, Decimal):
        return d
    scaled = (d * (Decimal(10) ** exponent(currency))).to_integral_value(rounding=ROUND_FLOOR)
    return int(scaled)


def percent_to_bps(value: object) -> Parsed:
    """'12.5' -> 1250. Fractions of a basis point are kept so the rules can reject them."""
    d = _decimal(value)
    if not isinstance(d, Decimal):
        return d
    return _as_number(d * 100)


def to_number(value: object) -> Parsed:
    d = _decimal(value)
    if not isinstance(d, Decimal):
        return d
    return _as_number(d)


def format_minor(amount: int, currency: str) -> str:
    """1500050, 'KES' -> 'KES 15,000.50'."""
    exp = exponent(currency)
    sign = "-" if amount < 0 else ""
    whole, frac = divmod(abs(int(amount)), 10**exp)
    text = f"{whole:,}"
    if exp:
        text += "." + str(frac).zfill(exp)
    return f"{currency} {sign}{text}"


def format_exact(numerator: int, denominator: int, currency: str) -> str:
    """An exact amount that may include fractions of a minor unit, for explanations."""
    exp = exponent(currency)
    d = Decimal(numerator) / Decimal(denominator) / (Decimal(10) ** exp)
    text = format(d.normalize(), "f")
    if "." in text:
        whole, frac = text.split(".")
        frac = frac.ljust(exp, "0")
    else:
        whole, frac = text, "0" * exp
    whole_fmt = f"{int(whole):,}"
    return f"{currency} {whole_fmt}.{frac}" if exp else f"{currency} {whole_fmt}"


def format_bps(bps: int | float) -> str:
    """5500 -> '55.00%'."""
    return f"{Decimal(str(bps)) / 100:.2f}%"
