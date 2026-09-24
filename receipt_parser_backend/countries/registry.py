"""Static country profile registry (spec Section 5).

v1 ships US and FR. Prompt text is copied verbatim from spec Section 5.2 so
the source of truth stays the spec, not this module.
"""

from __future__ import annotations

from receipt_parser_backend.countries.profile import CountryProfile

US = CountryProfile(
    code="US",
    name="United States",
    default_currency="USD",
    date_format="MM/DD/YYYY",
    decimal_separator=".",
    thousands_separator=",",
    tax_model="additive",
    total_tolerance=0.02,
    extraction_prompt=(
        "This is a receipt from the United States. Dates are usually written "
        "MM/DD/YYYY or MM/DD/YY. Decimal separator is a period. Item prices are "
        'usually shown before tax; sales tax appears as a separate line ("TAX", '
        '"SALES TAX"). Extract the final amount paid as `total` (often "TOTAL", '
        '"BALANCE DUE", "AMOUNT DUE"), not the subtotal. Record discounts '
        '("SAVINGS", "COUPON", "DISCOUNT") as a positive number in `discounts`. '
        'Do not treat payment lines ("VISA", "CHANGE", "CASH") as items. Leave '
        "any field you cannot read as null; never guess."
    ),
    interpreter_prompt=(
        'The user is in the United States. Interpret dates like "9/20" as '
        "September 20. Numbers use a period as the decimal separator."
    ),
)

FR = CountryProfile(
    code="FR",
    name="France",
    default_currency="EUR",
    date_format="DD/MM/YYYY",
    decimal_separator=",",
    thousands_separator=" ",
    tax_model="inclusive",
    total_tolerance=0.02,
    extraction_prompt=(
        "This is a receipt from France. Dates are written DD/MM/YYYY or "
        "DD/MM/YY. The decimal separator is a comma. Item prices include VAT "
        "(TTC). VAT (TVA) may be summarized in a table by rate with letter "
        "codes next to items; record the total VAT amount in `tax`. Extract "
        'the final amount paid as `total` (often "TOTAL", "TOTAL TTC", "NET À '
        'PAYER"), not "TOTAL HT". Record discounts ("REMISE", "RÉDUCTION", '
        '"BON D\'ACHAT") as a positive number in `discounts`. Do not treat '
        'payment lines ("CB", "CARTE BANCAIRE", "ESPÈCES", "RENDU") as items. '
        "Leave any field you cannot read as null; never guess."
    ),
    interpreter_prompt=(
        'The user is in France. Interpret dates like "20/9" as 20 September. '
        'Numbers may use a comma as the decimal separator ("3,49" means 3.49). '
        "The user may reply in French or English."
    ),
)

_PROFILES: dict[str, CountryProfile] = {profile.code: profile for profile in (US, FR)}


def get_profile(code: str) -> CountryProfile:
    """Return the profile for ``code``, or raise ``KeyError`` if unsupported."""

    try:
        return _PROFILES[code]
    except KeyError:
        raise KeyError(f"unsupported country code: {code!r}") from None


def supported_codes() -> list[str]:
    """Return the codes of every supported country, for ``/country`` listings."""

    return list(_PROFILES)
