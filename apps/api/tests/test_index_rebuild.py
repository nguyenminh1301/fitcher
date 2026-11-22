"""Packs whose search index is missing at api start, as after the move of search into ClickHouse."""

from app.api.runtime import packs_missing_their_index
from app.packs.search_indices import INDEX_NAMES, alias_name


def _compiled(root, *packs):
    for pack in packs:
        (root / "build" / pack).mkdir(parents=True)
        (root / "build" / pack / "compiled.json").write_text("{}", encoding="utf-8")
        (root / "packs" / pack).mkdir(parents=True)


def test_only_packs_with_a_missing_collection_are_compiled_again_the_active_one_first(tmp_path):
    _compiled(tmp_path, "alpha", "beta", "gamma")
    live = {alias_name("alpha", index) for index in INDEX_NAMES} | {alias_name("gamma", "metrics")}

    assert packs_missing_their_index(tmp_path / "build", tmp_path / "packs", live, "gamma") == ["gamma", "beta"]


def test_a_pack_being_compiled_or_without_its_files_is_left_alone(tmp_path):
    _compiled(tmp_path, "alpha", "beta")
    (tmp_path / "build" / "alpha" / "compiling").write_text("now", encoding="utf-8")
    (tmp_path / "packs" / "beta").rmdir()

    assert packs_missing_their_index(tmp_path / "build", tmp_path / "packs", set(), "alpha") == []
