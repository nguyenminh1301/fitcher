"""BM25 sparse terms and vectors for English and Vietnamese text."""

from app.search.sparse import average_length, document_vector, query_vector, terms, trigrams


def test_vietnamese_tokens_are_kept_as_written_and_folded():
    assert terms("Doanh thu thuần") == ["doanh", "thu", "thuần", "thuan"]
    assert set(terms("doanh thu thuan")) <= set(terms("Doanh Thu Thuần"))
    assert "khu" in terms("khu vực") and "vuc" in terms("khu vực")


def test_identifiers_and_column_names_match_whole_and_in_parts():
    assert terms("net_sales") == ["net_sales", "net", "sales"]
    assert {"customer_segment", "customer", "segment"} <= set(terms("sales_lines.customer_segment"))


def test_english_terms_are_lower_case_words():
    assert terms("Net Sales, by REGION!") == ["net", "sales", "by", "region"]


def test_query_and_document_vectors_share_indices_for_shared_terms():
    document = document_vector(terms("Doanh thu thuần: tiền bán hàng"), average_length=6)
    query = query_vector(terms("doanh thu"))
    assert set(query["indices"]) <= set(document["indices"])
    assert query["values"] == [1.0] * len(query["indices"])
    assert document["indices"] == sorted(document["indices"])


def test_bm25_saturates_repeats_and_favours_short_documents():
    once = dict(zip(*document_vector(["revenue"], 1).values()))
    many = dict(zip(*document_vector(["revenue"] * 5, 1).values()))
    [index] = once
    assert once[index] < many[index] < 2.2  # k1 + 1 bounds the term-frequency part
    short = dict(zip(*document_vector(["revenue", "x"], 4).values()))[index]
    long = dict(zip(*document_vector(["revenue", *["x"] * 10], 4).values()))[index]
    assert short > long


def test_trigrams_survive_a_misspelling():
    shared = set(trigrams("Electronics")) & set(trigrams("Electornics"))
    assert len(shared) >= len(set(trigrams("Electronics"))) // 2
    assert set(trigrams("Đông Nam")) == set(trigrams("dong nam"))


def test_average_length_of_no_documents_is_one():
    assert average_length([]) == 1.0
    assert average_length([["a", "b"], ["c"]]) == 1.5
