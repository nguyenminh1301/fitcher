"""The objects built for each pack: kept per pack name, dropped when that pack is compiled again."""

from app.api import runtime


def test_two_packs_keep_their_own_objects_and_a_reload_drops_only_the_one_named(monkeypatch):
    closed = []

    class Agent:
        def __init__(self, settings, compiled, screener, documents):
            self.compiled = compiled

        def close(self):
            closed.append(self.compiled)

    runtime.reload_pack()
    loads = []
    monkeypatch.setattr(runtime, "Agent", Agent)
    monkeypatch.setattr(runtime, "load_compiled", lambda directory, name: loads.append(name) or f"compiled {name}")
    monkeypatch.setattr(runtime, "get_screener", lambda: None)
    monkeypatch.setattr(runtime, "last_used_pack", lambda: "shop")

    first = runtime.get_agent()
    with runtime.serving("music"):
        second = runtime.get_agent()
        assert runtime.get_compiled() == "compiled music"
    assert runtime.get_agent() is first and first.compiled == "compiled shop" and second.compiled == "compiled music"
    assert loads == ["shop", "music"]

    runtime.reload_pack("music")

    assert closed == ["compiled music"]
    assert runtime.get_agent() is first
    with runtime.serving("music"):
        assert runtime.get_agent() is not second
    runtime.reload_pack()
    assert closed == ["compiled music", "compiled shop", "compiled music"]
    for dependency in runtime.PACK_DEPENDENCIES:
        assert len(dependency) == 0


def test_a_source_pack_is_ready_building_failed_or_none(monkeypatch, tmp_path):
    from types import SimpleNamespace

    runtime.reload_pack()
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "compiled.json").write_text("{}")
    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path))
    compiled = SimpleNamespace(pack=SimpleNamespace(datasets=SimpleNamespace(datasets=["a", "b"])))
    monkeypatch.setattr(runtime, "load_compiled", lambda directory, name: compiled)
    jobs = {"music": SimpleNamespace(status="failed", error="the model did not answer"),
            "films": SimpleNamespace(status="running", error=None),
            "shop": SimpleNamespace(status="failed", error="a rebuild failed")}

    class Pipeline:
        def latest_job(self, source_id):
            return jobs.get(source_id)

    monkeypatch.setattr(runtime, "get_instant_pipeline", type("Built", (), {
        "__call__": lambda self: Pipeline(), "cache_info": lambda self: SimpleNamespace(currsize=1)})())

    assert runtime.pack_status("shop") == ("ready", 2, "a rebuild failed")
    assert runtime.pack_status("music") == ("failed", 0, "the model did not answer")
    assert runtime.pack_status("films") == ("building", 0, None)
    assert runtime.pack_status("books") == ("none", 0, None)
    runtime.reload_pack()
