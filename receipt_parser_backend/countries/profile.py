"""Country profile shape (spec Section 5.1).

Country-specific behavior lives entirely in these profiles, never in
conditionals elsewhere in the pipeline (design rule 5). Adding a country means
adding an entry to :mod:`receipt_parser_backend.countries.registry`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

TaxModel = Literal["additive", "inclusive"]


class CountryProfile(BaseModel):
    """Per-country configuration and prompts."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    default_currency: str
    date_format: str
    decimal_separator: str
    thousands_separator: str
    tax_model: TaxModel
    total_tolerance: float
    extraction_prompt: str
    interpreter_prompt: str
