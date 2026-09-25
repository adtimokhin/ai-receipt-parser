"""Non-AI 529 expense report builder: a summary table plus one page per receipt.

Pure aggregation and PDF assembly - no AI touchpoint, per the user's explicit
"non-AI report builder" requirement. Categorization already happened at
receipt-save time (an optional, user-set ``category`` field, spec-adjacent
addition); this only reads what's already there and never infers a category
itself. A receipt with no category, or outside the date range, never reaches
this module at all - that filtering happens in the repository query.
"""

from __future__ import annotations

import io
from collections import defaultdict

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import letter  # type: ignore[import-untyped]
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
from reportlab.lib.units import inch  # type: ignore[import-untyped]
from reportlab.lib.utils import ImageReader  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from receipt_parser_backend.blob_storage.client import download_bytes
from receipt_parser_backend.receipts.models import Receipt

_CATEGORY_LABELS = {"room": "Room", "board": "Board"}


async def build_report_pdf(receipts: list[Receipt], start_date: str, end_date: str) -> bytes:
    """Build the full report: a summary page, then one labeled page (plus the
    original) per receipt, in the order given."""

    writer = PdfWriter()
    _append_pdf(writer, _build_summary_pdf(receipts, start_date, end_date))

    for receipt in receipts:
        _append_pdf(writer, _build_label_page(receipt))
        original_bytes = await download_bytes(receipt.files.original_r2_key)
        if receipt.files.original_content_type == "application/pdf":
            _append_pdf(writer, original_bytes)
        else:
            _append_pdf(writer, _build_image_page(original_bytes))

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _append_pdf(writer: PdfWriter, pdf_bytes: bytes) -> None:
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        writer.add_page(page)


def _build_summary_pdf(receipts: list[Receipt], start_date: str, end_date: str) -> bytes:
    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    story = [
        Paragraph("529 Expense Report", styles["Title"]),
        Paragraph(f"{start_date} to {end_date}", styles["Normal"]),
        Spacer(1, 0.25 * inch),
    ]

    table_data: list[list[str]] = [["Vendor", "Type", "Total"]]
    category_subtotals: dict[tuple[str, str], float] = defaultdict(float)
    for receipt in receipts:
        assert receipt.category is not None  # filtered by the repository query
        assert receipt.total is not None  # required before a receipt can be saved
        table_data.append(
            [
                receipt.merchant_name or "?",
                _CATEGORY_LABELS[receipt.category],
                f"{receipt.total:.2f} {receipt.currency}",
            ]
        )
        category_subtotals[(receipt.category, receipt.currency)] += receipt.total

    table = Table(table_data, colWidths=[2.5 * inch, 1 * inch, 1.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.25 * inch))

    # Subtotals per category, and a grand total - both grouped by currency
    # rather than summed across currencies, which would silently be wrong.
    for (category, currency), subtotal in sorted(category_subtotals.items()):
        story.append(
            Paragraph(
                f"{_CATEGORY_LABELS[category]} total: {subtotal:.2f} {currency}", styles["Normal"]
            )
        )
    grand_totals: dict[str, float] = defaultdict(float)
    for (_category, currency), subtotal in category_subtotals.items():
        grand_totals[currency] += subtotal
    story.append(Spacer(1, 0.1 * inch))
    for currency, total in sorted(grand_totals.items()):
        story.append(Paragraph(f"Grand total: {total:.2f} {currency}", styles["Normal"]))

    doc.build(story)
    return buffer.getvalue()


def _build_label_page(receipt: Receipt) -> bytes:
    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    assert receipt.category is not None
    assert receipt.total is not None
    story = [
        Paragraph(receipt.merchant_name or "Unknown merchant", styles["Heading2"]),
        Paragraph(f"Date: {receipt.date or '?'}", styles["Normal"]),
        Paragraph(f"Type: {_CATEGORY_LABELS[receipt.category]}", styles["Normal"]),
        Paragraph(f"Total: {receipt.total:.2f} {receipt.currency}", styles["Normal"]),
    ]
    doc.build(story)
    return buffer.getvalue()


def _build_image_page(image_bytes: bytes) -> bytes:
    """A single page with ``image_bytes`` scaled to fit, centered."""

    reader = ImageReader(io.BytesIO(image_bytes))
    image_width, image_height = reader.getSize()
    page_width, page_height = letter
    margin = 0.5 * inch
    max_width, max_height = page_width - 2 * margin, page_height - 2 * margin
    scale = min(max_width / image_width, max_height / image_height, 1.0)
    draw_width, draw_height = image_width * scale, image_height * scale
    x = (page_width - draw_width) / 2
    y = (page_height - draw_height) / 2

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.drawImage(reader, x, y, width=draw_width, height=draw_height)
    c.showPage()
    c.save()
    return buffer.getvalue()
