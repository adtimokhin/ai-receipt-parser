"""Normalizer (spec Section 8, Step 4).

Country-aware parsing driven entirely by the country profile's own fields
(``date_format``, ``decimal_separator``, ``thousands_separator``,
``default_currency``) - never a country conditional in this file (design
rule 5). Anything that can't be parsed with confidence is left ``None``
rather than guessed, per spec.
"""

from __future__ import annotations

import re
from datetime import date

from receipt_parser_backend.ai.extraction import RawExtraction
from receipt_parser_backend.countries import CountryProfile
from receipt_parser_backend.receipts.models import Draft, Item

_CURRENCY_SYMBOL_ALIASES: dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
}

_DATE_TOKEN_RE = re.compile(r"\d+")
_DATE_FORMAT_FIELD_RE = re.compile(r"[A-Za-z]+")
_DATE_FIELD_NAMES = {"M": "month", "D": "day", "Y": "year"}
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?")


def normalize_extraction(raw: RawExtraction, profile: CountryProfile) -> Draft:
    """Turn a raw extraction into a typed :class:`Draft` (spec Step 4)."""

    items = [
        Item(name=_clean_text(item.name), price=_parse_number(item.price, profile))
        for item in raw.items
        if item.name is not None or item.price is not None
    ]
    total = _parse_number(raw.total, profile)

    return Draft(
        merchant_name=_clean_text(raw.merchant_name),
        currency=_normalize_currency(raw.currency, profile),
        date=_parse_date(raw.date, profile),
        time=_parse_time(raw.time),
        items=items,
        discounts=_parse_number(raw.discounts, profile),
        tax=_parse_number(raw.tax, profile),
        total=total,
        total_source="extracted" if total is not None else None,
    )


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_currency(raw_currency: str | None, profile: CountryProfile) -> str:
    """Map a printed currency symbol/code to ISO 4217 (spec Step 4)."""

    if raw_currency is None:
        return profile.default_currency
    stripped = raw_currency.strip()
    if not stripped:
        return profile.default_currency
    upper = stripped.upper()
    if len(upper) == 3 and upper.isalpha():
        return upper  # already looks like an ISO code
    return _CURRENCY_SYMBOL_ALIASES.get(stripped, profile.default_currency)


def _parse_number(value: float | str | None, profile: CountryProfile) -> float | None:
    """Parse a price/tax/discount/total using the profile's separators."""

    if value is None:
        return None
    if isinstance(value, float):
        return value
    cleaned = value.strip().replace("\xa0", " ")
    if profile.thousands_separator:
        cleaned = cleaned.replace(profile.thousands_separator, "")
    if profile.decimal_separator != ".":
        cleaned = cleaned.replace(profile.decimal_separator, ".")
    try:
        return float(cleaned)
    except ValueError:
        return None  # unparseable; never guess


def _date_field_order(date_format: str) -> tuple[str, str, str] | None:
    tokens = _DATE_FORMAT_FIELD_RE.findall(date_format)
    if len(tokens) != 3:
        return None
    try:
        fields = tuple(_DATE_FIELD_NAMES[token[0].upper()] for token in tokens)
    except KeyError:
        return None
    if set(fields) != {"month", "day", "year"}:
        return None
    return fields  # type: ignore[return-value]


def _parse_date(raw_date: str | None, profile: CountryProfile) -> str | None:
    """Parse a printed date using the profile's field order (spec Step 4)."""

    if raw_date is None:
        return None
    parts = _DATE_TOKEN_RE.findall(raw_date)
    if len(parts) != 3:
        return None
    order = _date_field_order(profile.date_format)
    if order is None:
        return None
    values = dict(zip(order, (int(part) for part in parts), strict=True))
    year = values["year"]
    if year < 100:
        year += 2000  # v1 only ever sees recent receipts
    try:
        return date(year, values["month"], values["day"]).isoformat()
    except ValueError:
        return None  # not a real calendar date; never guess


def _parse_time(raw_time: str | None) -> str | None:
    """Parse a printed time, including an optional AM/PM suffix, to 24-hour ``HH:MM``."""

    if raw_time is None:
        return None
    match = _TIME_RE.search(raw_time)
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    meridiem = match.group(3)
    if meridiem:
        meridiem = meridiem.upper()
        if meridiem == "PM" and hour != 12:
            hour += 12
        elif meridiem == "AM" and hour == 12:
            hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"
