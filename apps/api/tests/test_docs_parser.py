import pytest

from app.onboarding import docs_parser
from app.onboarding.docs_parser import (
    DOCX, MARKDOWN, PDF, TEXT, XLSX, DocumentRejected, detect_media_type, parse_document,
)
from document_fixtures import MARKDOWN as MARKDOWN_BYTES, docx_bytes, pdf_bytes, xlsm_bytes, xlsx_bytes, zip_bytes


@pytest.mark.parametrize(("data", "name", "expected"), [
    (pdf_bytes(["Hello"]), "handbook.pdf", PDF),
    (docx_bytes(), "policy.docx", DOCX),
    (xlsx_bytes(), "codes.xlsx", XLSX),
    (MARKDOWN_BYTES, "glossary.md", MARKDOWN),
    (b"plain words", "notes.txt", TEXT),
    # The type comes from the content, not the name.
    (pdf_bytes(["Hello"]), "renamed.txt", PDF),
    ("﻿Xin chào".encode("utf-8"), "vi.txt", TEXT),
])
def test_media_type_comes_from_the_content(data, name, expected):
    assert detect_media_type(data, name) == expected


@pytest.mark.parametrize(("data", "name", "status", "message"), [
    (b"", "empty.txt", 422, "empty"),
    (xlsm_bytes(), "codes.xlsx", 415, "macro"),
    (zip_bytes(), "handbook.pdf", 415, "not a supported"),
    (b"\x89PNG\r\n\x1a\n\x00\x00", "scan.png", 415, "not a supported"),
    ("caf\xe9".encode("latin-1"), "notes.txt", 422, "UTF-8"),
])
def test_unsupported_or_unsafe_files_are_rejected(data, name, status, message):
    with pytest.raises(DocumentRejected, match=message) as raised:
        detect_media_type(data, name)
    assert raised.value.status == status


def test_pdf_pages_become_sections():
    sections = parse_document(pdf_bytes(["Gross margin is revenue\nminus cost.", "Second page."]), PDF)
    assert [section.heading_path for section in sections] == [["page 1"], ["page 2"]]
    assert "Gross margin is revenue" in sections[0].text


def test_pdf_without_a_text_layer_is_rejected():
    with pytest.raises(DocumentRejected, match="no text layer") as raised:
        parse_document(pdf_bytes(["", ""]), PDF)
    assert raised.value.status == 422


def test_pdf_page_cap(monkeypatch):
    monkeypatch.setattr(docs_parser, "MAX_PDF_PAGES", 1)
    with pytest.raises(DocumentRejected, match="more than 1 pages"):
        parse_document(pdf_bytes(["a", "b"]), PDF)


def test_docx_sections_follow_headings():
    sections = parse_document(docx_bytes(), DOCX)
    assert [(section.heading_path, section.text) for section in sections] == [
        (["Returns policy"], "A customer may return an item within 30 days."),
        (["Returns policy", "Refunds"], "Refunds go back to the original payment method."),
        (["Exchanges"], "Exchanges follow the same window."),
    ]


def test_markdown_sections_follow_headings_outside_code():
    sections = parse_document(MARKDOWN_BYTES, MARKDOWN)
    assert [section.heading_path for section in sections] == [
        ["Glossary"], ["Glossary", "Net sales"], ["Glossary", "Returns"],
    ]
    assert "# not a heading inside code" in sections[1].text


def test_text_is_one_section():
    sections = parse_document(b"First paragraph.\n\nSecond paragraph.", TEXT)
    assert len(sections) == 1 and sections[0].heading_path == []


def test_xlsx_sheets_keep_values_and_their_header_without_evaluating_formulas():
    sections = parse_document(xlsx_bytes(rows=2), XLSX)
    assert len(sections) == 1
    section = sections[0]
    assert section.heading_path == ["Codes"]
    assert section.header == "code | meaning"
    # A formula is neither evaluated nor kept as text: only a value the workbook stored is read.
    assert section.text.splitlines() == ["C0 | meaning of code 0", "C1 | meaning of code 1", "SUM"]


def test_xlsx_row_cap(monkeypatch):
    monkeypatch.setattr(docs_parser, "MAX_SHEET_ROWS", 2)
    with pytest.raises(DocumentRejected, match="more than 2 rows"):
        parse_document(xlsx_bytes(rows=5), XLSX)


def test_a_document_without_text_is_rejected():
    with pytest.raises(DocumentRejected, match="no text"):
        parse_document(b"   \n\n  ", TEXT)
