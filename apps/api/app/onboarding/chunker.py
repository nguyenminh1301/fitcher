"""Split parsed document sections into ``kb_docs`` chunks of at most ``max_chars`` characters.

A chunk never spans two sections, so Markdown and DOCX chunks stay under one
heading and PDF chunks on one page. Inside a section, paragraphs (blank-line
separated) are packed together up to the cap and a paragraph longer than the
cap is cut at word boundaries. Sheet rows are packed in blocks that each
start with the sheet's header row, so every chunk names its columns.
"""

from dataclasses import dataclass
import re

from app.onboarding.docs_parser import Section

DEFAULT_MAX_CHARS = 2000
_PARAGRAPHS = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    heading_path: list[str]
    text: str


def _cut(text: str, max_chars: int) -> list[str]:
    """Split one over-long piece at whitespace, or hard at the cap when a word is longer than it."""
    pieces: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:max_chars])
            word = word[max_chars:]
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


def _pack(units: list[str], max_chars: int, separator: str, prefix: str = "") -> list[str]:
    room = max_chars - len(prefix)
    packed: list[str] = []
    current = ""
    for unit in units:
        for piece in ([unit] if len(unit) <= room else _cut(unit, room)):
            candidate = f"{current}{separator}{piece}" if current else piece
            if len(candidate) <= room:
                current = candidate
            else:
                packed.append(prefix + current)
                current = piece
    if current:
        packed.append(prefix + current)
    return packed


def chunk_sections(sections: list[Section], media_type: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    """Chunks of every section in order; ``media_type`` is accepted for callers and kept for future formats."""
    del media_type  # every format is chunked by its sections; sheets are recognised by their header
    chunks: list[Chunk] = []
    for section in sections:
        if section.header is not None:
            rows = [line for line in section.text.splitlines() if line.strip()]
            texts = _pack(rows, max_chars, "\n", prefix=f"{section.header}\n")
        else:
            paragraphs = [part.strip() for part in _PARAGRAPHS.split(section.text) if part.strip()]
            texts = _pack(paragraphs, max_chars, "\n\n")
        chunks.extend(Chunk(list(section.heading_path), text) for text in texts)
    return chunks
