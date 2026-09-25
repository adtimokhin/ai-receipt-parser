"""Non-AI 529 report builder: PDF assembly, categorization math, and currency grouping."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

from receipt_parser_backend import reports
from receipt_parser_backend.receipts.models import Receipt, ReceiptFiles
from receipt_parser_backend.reports.builder import build_report_pdf

_ = reports  # imported for its side-effect-free package marker; keeps ruff happy


def _tiny_jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (100, 150), color="white").save(buf, format="JPEG")
    return buf.getvalue()


def _tiny_pdf(*page_texts: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for text in page_texts:
        c.drawString(100, 700, text)
        c.showPage()
    c.save()
    return buf.getvalue()


def _receipt(
    *,
    merchant_name: str,
    total: float,
    category: str,
    currency: str = "USD",
    r2_key: str,
    content_type: str = "image/jpeg",
) -> Receipt:
    return Receipt(
        telegram_user_id=1,
        country_code="US",
        merchant_name=merchant_name,
        currency=currency,
        date="2026-01-15",
        total=total,
        category=category,
        files=ReceiptFiles(original_r2_key=r2_key, original_content_type=content_type),
        created_at=datetime.now(UTC),
    )


def _stub_downloads(monkeypatch: pytest.MonkeyPatch, contents: dict[str, bytes]) -> None:
    async def _fake_download_bytes(key: str) -> bytes:
        return contents[key]

    monkeypatch.setattr(
        "receipt_parser_backend.reports.builder.download_bytes", _fake_download_bytes
    )


async def test_empty_receipt_list_produces_just_the_summary_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = await build_report_pdf([], "2026-01-01", "2026-01-31")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "529 Expense Report" in text
    assert "2026-01-01 to 2026-01-31" in text


async def test_image_receipt_produces_a_label_and_image_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jpeg = _tiny_jpeg()
    _stub_downloads(monkeypatch, {"k1": jpeg})
    receipt = _receipt(merchant_name="Landlord LLC", total=1200.0, category="room", r2_key="k1")

    pdf_bytes = await build_report_pdf([receipt], "2026-01-01", "2026-01-31")
    reader = PdfReader(io.BytesIO(pdf_bytes))

    # summary + label + image
    assert len(reader.pages) == 3
    label_text = reader.pages[1].extract_text()
    assert "Landlord LLC" in label_text
    assert "Room" in label_text
    assert "1200.00 USD" in label_text


async def test_pdf_receipt_pages_are_merged_directly_not_rasterized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_pdf = _tiny_pdf("Original page one", "Original page two")
    _stub_downloads(monkeypatch, {"k1": original_pdf})
    receipt = _receipt(
        merchant_name="Grocer",
        total=42.0,
        category="board",
        r2_key="k1",
        content_type="application/pdf",
    )

    pdf_bytes = await build_report_pdf([receipt], "2026-01-01", "2026-01-31")
    reader = PdfReader(io.BytesIO(pdf_bytes))

    # summary + label + 2 original pages
    assert len(reader.pages) == 4
    assert "Original page one" in reader.pages[2].extract_text()
    assert "Original page two" in reader.pages[3].extract_text()


async def test_summary_table_lists_vendor_type_and_total(monkeypatch: pytest.MonkeyPatch) -> None:
    jpeg = _tiny_jpeg()
    _stub_downloads(monkeypatch, {"k1": jpeg, "k2": jpeg})
    receipts = [
        _receipt(merchant_name="Landlord LLC", total=1200.0, category="room", r2_key="k1"),
        _receipt(merchant_name="Trader Joes", total=85.32, category="board", r2_key="k2"),
    ]

    pdf_bytes = await build_report_pdf(receipts, "2026-01-01", "2026-01-31")
    text = PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()

    assert "Landlord LLC" in text
    assert "Trader Joes" in text
    assert "Room total: 1200.00 USD" in text
    assert "Board total: 85.32 USD" in text
    assert "Grand total: 1285.32 USD" in text


async def test_subtotals_are_grouped_by_currency_not_summed_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jpeg = _tiny_jpeg()
    _stub_downloads(monkeypatch, {"k1": jpeg, "k2": jpeg})
    receipts = [
        _receipt(
            merchant_name="US Landlord", total=1000.0, category="room", r2_key="k1", currency="USD"
        ),
        _receipt(
            merchant_name="FR Landlord", total=800.0, category="room", r2_key="k2", currency="EUR"
        ),
    ]

    pdf_bytes = await build_report_pdf(receipts, "2026-01-01", "2026-01-31")
    text = PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()

    assert "Room total: 1000.00 USD" in text
    assert "Room total: 800.00 EUR" in text
    assert "Grand total: 1000.00 USD" in text
    assert "Grand total: 800.00 EUR" in text
    assert "1800.00" not in text  # never incorrectly summed across currencies
