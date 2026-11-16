from app.packs.search_indices import INDEX_NAMES, alias_name
from jobs import compare_search_engines as job
from tests.fakes import FakeSearch


def test_copy_makes_an_identical_live_generation_of_every_collection():
    source, target = FakeSearch(), FakeSearch()
    for index in INDEX_NAMES:
        source.create(alias_name("shop", index), 3, 2)
    point = {"id": "p1", "vector": {"dense": [1.0, 0.0]}, "payload": {"id": "m.revenue", "allowed_roles": ["analyst"]}}
    source.write("shop_metrics", [point], 3)
    source.switch_live({alias_name("shop", index): 3 for index in INDEX_NAMES})
    target.create("shop_metrics", 1, 2)

    counts = job.copy_pack(source, target, "shop", 2)

    assert counts["shop_metrics"] == 1 and counts["shop_examples"] == 0
    assert target.live() == {alias_name("shop", index): 2 for index in INDEX_NAMES}
    assert target.live_points("shop_metrics", with_vectors=True) == [point]


def test_percentile_picks_the_nearest_rank():
    assert job.percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.5) == 3.0
    assert job.percentile(list(map(float, range(1, 101))), 0.95) == 95.0
