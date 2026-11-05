"""Small documents of every supported format, built in code so no binary file is committed."""

from io import BytesIO
import zipfile

from docx import Document
from openpyxl import Workbook


def pdf_bytes(pages: list[str]) -> bytes:
    """A minimal PDF whose pages draw ``pages`` with a base font; an empty string gives a page without text."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font = 3 + 2 * len(pages)
    for index, text in enumerate(pages):
        content = 4 + 2 * index
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode()
        )
        lines = [line.replace("(", "").replace(")", "") for line in text.split("\n")] if text else []
        body = "".join(f"BT /F1 12 Tf 72 {720 - 16 * n} Td ({line}) Tj ET\n" for n, line in enumerate(lines))
        stream = body.encode()
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def docx_bytes() -> bytes:
    document = Document()
    document.add_heading("Returns policy", level=1)
    document.add_paragraph("A customer may return an item within 30 days.")
    document.add_heading("Refunds", level=2)
    document.add_paragraph("Refunds go back to the original payment method.")
    document.add_heading("Exchanges", level=1)
    document.add_paragraph("Exchanges follow the same window.")
    out = BytesIO()
    document.save(out)
    return out.getvalue()


def xlsx_bytes(rows: int = 3, sheet: str = "Codes") -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.append(["code", "meaning"])
    for number in range(rows):
        worksheet.append([f"C{number}", f"meaning of code {number}"])
    worksheet.append(["SUM", "=1+1"])
    out = BytesIO()
    workbook.save(out)
    return out.getvalue()


def xlsm_bytes() -> bytes:
    """An xlsx with a VBA project added, as a macro-enabled workbook carries."""
    source = zipfile.ZipFile(BytesIO(xlsx_bytes()))
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr("xl/vbaProject.bin", b"\x00vba")
    return out.getvalue()


def zip_bytes() -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        target.writestr("notes.txt", "hello")
    return out.getvalue()


MARKDOWN = b"""# Glossary

Intro paragraph.

## Net sales

Net sales exclude cancelled orders.

```
# not a heading inside code
```

## Returns

Returned lines are counted on the return date.
"""
