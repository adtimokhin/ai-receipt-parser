"""Country profile registry smoke test (spec Section 5)."""

from __future__ import annotations

import pytest

from receipt_parser_backend.countries import get_profile, supported_codes
from receipt_parser_backend.countries.registry import FR, US


def test_supported_codes() -> None:
    assert set(supported_codes()) == {"US", "FR"}


def test_us_profile() -> None:
    profile = get_profile("US")
    assert profile is US
    assert profile.tax_model == "additive"
    assert profile.default_currency == "USD"
    assert profile.decimal_separator == "."
    assert "United States" in profile.extraction_prompt
    assert "United States" in profile.interpreter_prompt


def test_fr_profile() -> None:
    profile = get_profile("FR")
    assert profile is FR
    assert profile.tax_model == "inclusive"
    assert profile.default_currency == "EUR"
    assert profile.decimal_separator == ","
    assert "France" in profile.extraction_prompt
    assert "France" in profile.interpreter_prompt


def test_unsupported_code_raises() -> None:
    with pytest.raises(KeyError):
        get_profile("DE")
