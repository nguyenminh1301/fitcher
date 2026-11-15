"""Switching the active pack drops every long-lived object built for the previous one."""

from app.api import runtime


def test_reloading_the_pack_closes_the_agent_and_clears_the_pack_caches(monkeypatch):
    closed = []

    class Agent:
        def close(self):
            closed.append(True)

    runtime.get_agent.cache_clear()
    monkeypatch.setattr(runtime, "Agent", lambda *args: Agent())
    monkeypatch.setattr(runtime, "get_compiled", runtime.get_compiled)
    runtime.get_compiled.cache_clear()
    calls = []
    monkeypatch.setattr(runtime, "load_compiled", lambda directory, name: calls.append(name) or "compiled")
    monkeypatch.setattr(runtime, "current_pack", lambda: "shop")
    monkeypatch.setattr(runtime, "get_screener", lambda: None)
    runtime.get_compiled()
    runtime.get_agent()

    runtime.reload_pack()

    assert closed == [True]
    assert runtime.get_agent.cache_info().currsize == 0 and runtime.get_compiled.cache_info().currsize == 0
    for dependency in runtime.PACK_DEPENDENCIES:
        assert dependency.cache_info().currsize == 0
