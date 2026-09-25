"""Normalizer (spec Step 4): country-aware date/number/currency parsing."""

from __future__ import annotations

from receipt_parser_backend.ai.extraction import RawExtraction, RawExtractionItem
from receipt_parser_backend.countries.registry import FR, US
from receipt_parser_backend.pipeline.normalizer import normalize_extraction


def test_currency_falls_back_to_country_default_when_not_extracted() -> None:
    raw = RawExtraction(currency=None, total=1.0)
    draft = normalize_extraction(raw, US)
    assert draft.currency == US.default_currency


def test_extracted_iso_currency_code_is_kept() -> None:
    raw = RawExtraction(currency="eur", total=1.0)
    draft = normalize_extraction(raw, US)
    assert draft.currency == "EUR"


def test_dollar_symbol_maps_to_usd() -> None:
    raw = RawExtraction(currency="$", total=1.0)
    draft = normalize_extraction(raw, US)
    assert draft.currency == "USD"


def test_euro_symbol_maps_to_eur() -> None:
    raw = RawExtraction(currency="€", total=1.0)
    draft = normalize_extraction(raw, FR)
    assert draft.currency == "EUR"


def test_unrecognized_currency_falls_back_to_country_default() -> None:
    raw = RawExtraction(currency="???", total=1.0)
    draft = normalize_extraction(raw, US)
    assert draft.currency == US.default_currency


def test_items_with_neither_name_nor_price_are_dropped() -> None:
    raw = RawExtraction(
        items=[
            RawExtractionItem(name="Milk", price=1.5),
            RawExtractionItem(name=None, price=None),
        ]
    )
    draft = normalize_extraction(raw, US)
    assert len(draft.items) == 1
    assert draft.items[0].name == "Milk"


def test_item_with_only_a_price_is_kept() -> None:
    raw = RawExtraction(items=[RawExtractionItem(name=None, price=2.5)])
    draft = normalize_extraction(raw, US)
    assert len(draft.items) == 1
    assert draft.items[0].price == 2.5


def test_total_source_is_extracted_when_total_present() -> None:
    raw = RawExtraction(total=10.0)
    draft = normalize_extraction(raw, US)
    assert draft.total_source == "extracted"


def test_total_source_is_none_when_total_missing() -> None:
    raw = RawExtraction(total=None)
    draft = normalize_extraction(raw, US)
    assert draft.total_source is None


def test_merchant_name_is_trimmed() -> None:
    raw = RawExtraction(merchant_name="  Fake Mart  ")
    draft = normalize_extraction(raw, US)
    assert draft.merchant_name == "Fake Mart"


# --- dates: country-specific field order --------------------------------------


def test_us_date_format_mm_dd_yyyy() -> None:
    raw = RawExtraction(date="1/15/2026")
    draft = normalize_extraction(raw, US)
    assert draft.date == "2026-01-15"


def test_us_date_format_two_digit_year() -> None:
    raw = RawExtraction(date="1/15/26")
    draft = normalize_extraction(raw, US)
    assert draft.date == "2026-01-15"


def test_fr_date_format_dd_mm_yyyy() -> None:
    raw = RawExtraction(date="15/01/2026")
    draft = normalize_extraction(raw, FR)
    assert draft.date == "2026-01-15"


def test_same_digits_parse_differently_by_country() -> None:
    # 09/08/2026: US reads month/day -> Sept 8; FR reads day/month -> Aug 9.
    assert normalize_extraction(RawExtraction(date="09/08/2026"), US).date == "2026-09-08"
    assert normalize_extraction(RawExtraction(date="09/08/2026"), FR).date == "2026-08-09"


def test_unparseable_date_is_left_null_not_guessed() -> None:
    raw = RawExtraction(date="not a date")
    draft = normalize_extraction(raw, US)
    assert draft.date is None


def test_impossible_calendar_date_is_left_null() -> None:
    raw = RawExtraction(date="13/40/2026")  # no 13th month, no 40th day
    draft = normalize_extraction(raw, US)
    assert draft.date is None


def test_date_is_none_when_not_extracted() -> None:
    assert normalize_extraction(RawExtraction(date=None), US).date is None


# --- times ---------------------------------------------------------------------


def test_24_hour_time_passes_through() -> None:
    raw = RawExtraction(time="14:30")
    draft = normalize_extraction(raw, FR)
    assert draft.time == "14:30"


def test_pm_time_is_converted_to_24_hour() -> None:
    raw = RawExtraction(time="2:30 PM")
    draft = normalize_extraction(raw, US)
    assert draft.time == "14:30"


def test_12_am_is_midnight() -> None:
    raw = RawExtraction(time="12:00 AM")
    draft = normalize_extraction(raw, US)
    assert draft.time == "00:00"


def test_12_pm_is_noon() -> None:
    raw = RawExtraction(time="12:00 PM")
    draft = normalize_extraction(raw, US)
    assert draft.time == "12:00"


# --- numbers: decimal and thousands separators ---------------------------------


def test_us_decimal_point_parses_directly() -> None:
    raw = RawExtraction(total="1234.56")
    draft = normalize_extraction(raw, US)
    assert draft.total == 1234.56


def test_us_thousands_comma_is_stripped() -> None:
    raw = RawExtraction(total="1,234.56")
    draft = normalize_extraction(raw, US)
    assert draft.total == 1234.56


def test_fr_decimal_comma_is_converted() -> None:
    raw = RawExtraction(total="3,49")
    draft = normalize_extraction(raw, FR)
    assert draft.total == 3.49


def test_fr_thousands_space_is_stripped() -> None:
    raw = RawExtraction(total="1 234,56")
    draft = normalize_extraction(raw, FR)
    assert draft.total == 1234.56


def test_numeric_value_already_a_float_is_kept_as_is() -> None:
    raw = RawExtraction(total=12.34, tax=0.5, discounts=1.0)
    draft = normalize_extraction(raw, US)
    assert draft.total == 12.34
    assert draft.tax == 0.5
    assert draft.discounts == 1.0


def test_unparseable_number_is_left_null() -> None:
    raw = RawExtraction(total="not a number")
    draft = normalize_extraction(raw, US)
    assert draft.total is None


def test_item_price_uses_the_countrys_decimal_separator() -> None:
    raw = RawExtraction(items=[RawExtractionItem(name="Lait", price="1,15")])
    draft = normalize_extraction(raw, FR)
    assert draft.items[0].price == 1.15


# --- category: the extractor's auto-classification guess -----------------------


def test_category_room_is_kept() -> None:
    raw = RawExtraction(category="room")
    draft = normalize_extraction(raw, US)
    assert draft.category == "room"


def test_category_board_is_kept() -> None:
    raw = RawExtraction(category="board")
    draft = normalize_extraction(raw, US)
    assert draft.category == "board"


def test_category_is_case_insensitive() -> None:
    raw = RawExtraction(category="ROOM")
    draft = normalize_extraction(raw, US)
    assert draft.category == "room"


def test_category_none_stays_none() -> None:
    raw = RawExtraction(category=None)
    draft = normalize_extraction(raw, US)
    assert draft.category is None


def test_unrecognized_category_is_dropped_not_guessed() -> None:
    raw = RawExtraction(category="restaurant")
    draft = normalize_extraction(raw, US)
    assert draft.category is None
