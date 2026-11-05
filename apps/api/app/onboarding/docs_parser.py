"""Read company documents into text sections (DECISIONS §5 Company documents).

The media type comes from the file's content, never its name: PDF (text
layer only), DOCX, XLSX (cell values; formulas are not evaluated), Markdown
and UTF-8 plain text. Macro-enabled Office files, other archives and binary
files are refused. Files are parsed and never executed or served back, and
parsing stops at a page or row cap, so a large upload cannot exhaust the api.
Their text is data, never instructions (DECISIONS §9).
"""

from dataclasses import dataclass
from io import BytesIO
import re
import zipfile

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MARKDOWN = "text/markdown"
TEXT = "text/plain"
MEDIA_TYPES = (PDF, DOCX, XLSX, MARKDOWN, TEXT)
MAX_PDF_PAGES = 500
MAX_SHEET_ROWS = 50_000
_MARKDOWN_NAMES = (".md", ".markdown")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_DOCX_HEADING = re.compile(r"^Heading (\d)$")


class DocumentRejected(ValueError):
    """The file cannot be accepted; ``status`` is the HTTP status the api answers (415 type, 422 content)."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Section:
    heading_path: list[str]
    text: str
    # A sheet's header row, repeated at the top of every chunk of its rows.
    header: str | None = None


def _unsupported() -> DocumentRejected:
    return DocumentRejected("the file is not a supported type (PDF, DOCX, XLSX, Markdown or UTF-8 text)", 415)


def _office_type(data: bytes) -> str:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
        names = set(archive.namelist())
        content_types = archive.read("[Content_Types].xml").decode("utf-8", "replace") if "[Content_Types].xml" in names else ""
    except zipfile.BadZipFile:
        raise _unsupported() from None
    macro = any(name.endswith("vbaProject.bin") for name in names) or "macroEnabled" in content_types
    if "word/document.xml" in names or "xl/workbook.xml" in names:
        if macro:
            raise DocumentRejected("macro-enabled Office files are not accepted", 415)
        return DOCX if "word/document.xml" in names else XLSX
    raise _unsupported()


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentRejected("plain text must be UTF-8") from None


def detect_media_type(data: bytes, file_name: str) -> str:
    """The supported media type of ``data``; raise DocumentRejected otherwise."""
    if not data:
        raise DocumentRejected("the file is empty")
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"PK\x03\x04"):
        return _office_type(data)
    if b"\x00" in data[:8192]:
        raise _unsupported()
    _text(data)
    return MARKDOWN if file_name.lower().endswith(_MARKDOWN_NAMES) else TEXT


def _pdf(data: bytes) -> list[Section]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise DocumentRejected("encrypted PDFs are not accepted")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentRejected(f"the PDF has more than {MAX_PDF_PAGES} pages")
        sections = [Section([f"page {number}"], (page.extract_text() or "").strip())
                    for number, page in enumerate(reader.pages, start=1)]
    except PdfReadError as error:
        raise DocumentRejected(f"the PDF cannot be read: {error}") from None
    if not any(section.text for section in sections):
        raise DocumentRejected("the PDF has no text layer; scanned PDFs are not supported")
    return sections


class _Outline:
    """Collects text under the current heading path."""

    def __init__(self):
        self.path: list[str] = []
        self.lines: list[str] = []
        self.sections: list[Section] = []

    def heading(self, level: int, title: str) -> None:
        self.flush()
        self.path = [*self.path[:level - 1], title]

    def add(self, line: str) -> None:
        self.lines.append(line)

    def flush(self) -> None:
        text = "\n".join(self.lines).strip()
        if text:
            self.sections.append(Section(list(self.path), text))
        self.lines = []


def _docx(data: bytes) -> list[Section]:
    from docx import Document

    outline = _Outline()
    document = Document(BytesIO(data))
    for paragraph in document.paragraphs:
        style = paragraph.style.name if paragraph.style is not None else ""
        level = 1 if style == "Title" else int(match.group(1)) if (match := _DOCX_HEADING.match(style)) else 0
        if level and paragraph.text.strip():
            outline.heading(level, paragraph.text.strip())
        else:
            outline.add(paragraph.text)
    for table in document.tables:
        for row in table.rows:
            outline.add(" | ".join(cell.text.strip() for cell in row.cells))
    outline.flush()
    return outline.sections


def _markdown(text: str) -> list[Section]:
    outline = _Outline()
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        match = None if fenced else _HEADING.match(line)
        if match:
            outline.heading(len(match.group(1)), match.group(2))
        else:
            outline.add(line)
    outline.flush()
    return outline.sections


def _cell(value: object) -> str:
    return "" if value is None else " ".join(str(value).split())


def _xlsx(data: bytes) -> list[Section]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as error:  # noqa: BLE001 - openpyxl raises many types for a corrupt workbook
        raise DocumentRejected(f"the workbook cannot be read: {type(error).__name__}") from None
    sections: list[Section] = []
    total = 0
    try:
        for sheet in workbook.worksheets:
            header: str | None = None
            lines: list[str] = []
            for row in sheet.iter_rows(values_only=True):
                cells = [_cell(value) for value in row]
                if not any(cells):
                    continue
                total += 1
                if total > MAX_SHEET_ROWS:
                    raise DocumentRejected(f"the workbook has more than {MAX_SHEET_ROWS} rows")
                line = " | ".join(cells).rstrip(" |")
                if header is None:
                    header = line
                else:
                    lines.append(line)
            if header is not None:
                sections.append(Section([sheet.title], "\n".join(lines) or header, header=header))
    finally:
        workbook.close()
    return sections


def parse_document(data: bytes, media_type: str) -> list[Section]:
    """The document's non-empty sections; raise DocumentRejected when it has no readable text."""
    if media_type == PDF:
        sections = _pdf(data)
    elif media_type == DOCX:
        sections = _docx(data)
    elif media_type == XLSX:
        sections = _xlsx(data)
    elif media_type == MARKDOWN:
        sections = _markdown(_text(data))
    elif media_type == TEXT:
        text = _text(data).strip()
        sections = [Section([], text)] if text else []
    else:
        raise _unsupported()
    sections = [section for section in sections if section.text.strip()]
    if not sections:
        raise DocumentRejected("the document has no text")
    return sections
