"""Non-AI 529 expense report builder: an .xlsx breaking rent and food out separately.

A companion to ``builder.py``'s PDF (which carries the receipt photos and a
printed table) - this is the literal spreadsheet the original ask specified,
sent as a second Telegram document. Pure aggregation, same as the PDF: no AI
touchpoint, and a receipt only ever appears here because the repository query
already filtered it to a categorized, in-range receipt.
"""

from __future__ import annotations

import io
from collections import defaultdict

from openpyxl import Workbook  # type: ignore[import-untyped]
from openpyxl.styles import Font  # type: ignore[import-untyped]
from openpyxl.worksheet.worksheet import Worksheet  # type: ignore[import-untyped]

from receipt_parser_backend.receipts.models import Receipt

_SHEET_TITLES = {"room": "Room (Rent)", "board": "Board (Food)"}
_HEADER = ["Vendor", "Date", "Time", "Total", "Currency"]


def build_report_xlsx(receipts: list[Receipt], start_date: str, end_date: str) -> bytes:
    """One sheet per category (room, board), each with its own rows and
    per-currency subtotal(s), plus a summary sheet up front."""

    workbook = Workbook()
    summary_sheet: Worksheet = workbook.active
    summary_sheet.title = "Summary"
    _write_summary_sheet(summary_sheet, receipts, start_date, end_date)

    for category in ("room", "board"):
        category_receipts = [r for r in receipts if r.category == category]
        sheet: Worksheet = workbook.create_sheet(_SHEET_TITLES[category])
        _write_category_sheet(sheet, category_receipts)

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _write_summary_sheet(
    sheet: Worksheet, receipts: list[Receipt], start_date: str, end_date: str
) -> None:
    sheet.append([f"529 Expense Report: {start_date} to {end_date}"])
    sheet.append([])
    sheet.append(["Category", "Currency", "Total"])
    _bold_row(sheet, 3)

    subtotals: dict[tuple[str, str], float] = defaultdict(float)
    for receipt in receipts:
        assert receipt.category is not None  # filtered by the repository query
        assert receipt.total is not None  # required before a receipt can be saved
        subtotals[(receipt.category, receipt.currency)] += receipt.total

    for (category, currency), total in sorted(subtotals.items()):
        sheet.append([_SHEET_TITLES[category], currency, round(total, 2)])

    # Grand total per currency - never summed across currencies, same as the PDF.
    grand_totals: dict[str, float] = defaultdict(float)
    for (_category, currency), total in subtotals.items():
        grand_totals[currency] += total
    sheet.append([])
    for currency, total in sorted(grand_totals.items()):
        sheet.append(["Grand total", currency, round(total, 2)])


def _write_category_sheet(sheet: Worksheet, receipts: list[Receipt]) -> None:
    sheet.append(_HEADER)
    _bold_row(sheet, 1)

    subtotals: dict[str, float] = defaultdict(float)
    for receipt in receipts:
        assert receipt.total is not None  # required before a receipt can be saved
        sheet.append(
            [
                receipt.merchant_name or "?",
                receipt.date or "?",
                receipt.time or "?",
                round(receipt.total, 2),
                receipt.currency,
            ]
        )
        subtotals[receipt.currency] += receipt.total

    sheet.append([])
    for currency, total in sorted(subtotals.items()):
        sheet.append([None, None, "Subtotal", round(total, 2), currency])


def _bold_row(sheet: Worksheet, row_number: int) -> None:
    for cell in sheet[row_number]:
        cell.font = Font(bold=True)
