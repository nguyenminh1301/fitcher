from app.onboarding.chunker import chunk_sections
from app.onboarding.docs_parser import MARKDOWN, PDF, XLSX, Section


def test_small_sections_stay_whole_and_never_merge_across_headings():
    sections = [Section(["A"], "one"), Section(["A", "B"], "two")]
    chunks = chunk_sections(sections, MARKDOWN, max_chars=100)
    assert [(chunk.heading_path, chunk.text) for chunk in chunks] == [(["A"], "one"), (["A", "B"], "two")]


def test_paragraphs_are_packed_up_to_the_cap():
    text = "\n\n".join(f"paragraph {n} " + "x" * 30 for n in range(6))
    chunks = chunk_sections([Section(["page 1"], text)], PDF, max_chars=100)
    assert len(chunks) == 3
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert chunks[0].text.startswith("paragraph 0") and "paragraph 1" in chunks[0].text


def test_a_paragraph_longer_than_the_cap_is_cut():
    chunks = chunk_sections([Section([], "word " * 100)], PDF, max_chars=60)
    assert len(chunks) > 1
    assert all(0 < len(chunk.text) <= 60 for chunk in chunks)


def test_sheet_blocks_repeat_the_header_row():
    rows = "\n".join(f"C{n} | meaning of code {n}" for n in range(20))
    chunks = chunk_sections([Section(["Codes"], rows, header="code | meaning")], XLSX, max_chars=120)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith("code | meaning\n")
        assert len(chunk.text) <= 120
        assert chunk.heading_path == ["Codes"]
    assert sum(len(chunk.text.splitlines()) - 1 for chunk in chunks) == 20
