"""The owner and the active role on the HTTP endpoints, and the pack identity."""

from agent_fixtures import compiled_fixture
from fastapi.testclient import TestClient
import pytest

from session_fixtures import SessionHeaders

from app.api import runtime
from app.main import app


@pytest.fixture
def client():
    app.dependency_overrides[runtime.get_compiled] = compiled_fixture
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_me_is_the_owner_with_every_pack_role_and_console_role(client):
    response = client.get("/me")

    assert response.status_code == 200
    pack_roles = [role.id for role in compiled_fixture().pack.policies.roles]
    assert response.json() == {
        "user_id": "owner", "display_name": "Owner", "roles": [*pack_roles, "pack_reviewer", "admin"],
        "active_role": pack_roles[0], "exposed": False,
    }


def test_an_active_role_header_the_user_does_not_hold_is_forbidden(client):
    response = client.get("/me", headers={**SessionHeaders(), "X-Active-Role": "auditor"})

    assert response.status_code == 403


def test_pack_names_the_active_pack_and_its_roles_without_a_token(client):
    response = client.get("/pack")

    assert response.status_code == 200
    pack = compiled_fixture().pack
    assert response.json() == {
        "name": pack.name, "display_name": pack.business_profile.display_name,
        "roles": [role.id for role in pack.policies.roles],
    }


def test_a_pack_under_onboarding_is_named_from_its_pack_files(client, monkeypatch, tmp_path):
    from conftest import FIXTURE_PACK

    del app.dependency_overrides[runtime.get_compiled_or_none]
    runtime.reload_pack()
    monkeypatch.setenv("ACTIVE_PACK", "minimal")
    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path / "build"))
    monkeypatch.setenv("PACKS_DIR", str(FIXTURE_PACK.parent))

    assert client.get("/pack").json() == {"name": "minimal", "display_name": "Minimal widget shop", "roles": ["reader"]}
    me = client.get("/me").json()
    assert me["roles"] == ["reader", "pack_reviewer", "admin"] and me["active_role"] == "reader"


def test_an_uncompiled_pack_makes_the_endpoints_unavailable(client, monkeypatch, tmp_path):
    del app.dependency_overrides[runtime.get_compiled]
    del app.dependency_overrides[runtime.get_compiled_or_none]
    runtime.reload_pack()
    monkeypatch.setenv("ACTIVE_PACK", "demo")
    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path))
    monkeypatch.setenv("PACKS_DIR", str(tmp_path / "packs"))

    response = client.get("/pack")

    assert response.status_code == 503
    assert "compile the pack first" in response.json()["detail"]
    assert client.get("/me", headers=SessionHeaders()).status_code == 503
    runtime.reload_pack()


def test_suggestions_are_the_first_approved_example_questions_of_the_active_pack(client):
    response = client.get("/pack/suggestions", headers=SessionHeaders())

    examples = [example for example in compiled_fixture().pack.examples.examples][:3]
    assert response.status_code == 200
    assert response.json() == [{"text": example.question, "lang": example.language} for example in examples]


def test_a_new_instance_without_any_pack_still_knows_the_owner(client, monkeypatch):
    del app.dependency_overrides[runtime.get_compiled]
    del app.dependency_overrides[runtime.get_compiled_or_none]
    runtime.reload_pack()
    monkeypatch.setattr(runtime, "current_pack", lambda: "")

    response = client.get("/me")

    assert response.status_code == 200
    assert response.json()["active_role"] is None and response.json()["roles"] == ["pack_reviewer", "admin"]
    runtime.reload_pack()


def test_a_request_names_the_pack_it_reads_and_others_keep_the_pack_used_last(client, monkeypatch, tmp_path):
    from conftest import FIXTURE_PACK

    del app.dependency_overrides[runtime.get_compiled_or_none]
    runtime.reload_pack()
    monkeypatch.setenv("ACTIVE_PACK", "elsewhere")
    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path / "build"))
    monkeypatch.setenv("PACKS_DIR", str(FIXTURE_PACK.parent))

    named = client.get("/pack", params={"pack": "minimal"})
    default = client.get("/pack")

    assert named.status_code == 200 and named.json()["name"] == "minimal"
    assert default.status_code == 503 and "elsewhere" in default.json()["detail"]
    runtime.reload_pack()


def test_choosing_a_compiled_pack_makes_it_the_current_one(client, monkeypatch):
    chosen = []
    served = []
    monkeypatch.setattr(runtime, "get_compiled", lambda: served.append(runtime.current_pack()) or compiled_fixture())
    monkeypatch.setattr(runtime, "set_active_pack", lambda db, name: chosen.append(name))

    response = client.put("/pack", json={"name": "minimal"})

    assert response.status_code == 200 and response.json()["name"] == compiled_fixture().pack.name
    assert served == ["minimal"] and chosen == ["minimal"]


def test_a_pack_that_was_never_compiled_cannot_be_chosen(client, monkeypatch):
    chosen = []

    def missing():
        raise runtime.unavailable("compile the pack first")

    monkeypatch.setattr(runtime, "get_compiled", missing)
    monkeypatch.setattr(runtime, "set_active_pack", lambda db, name: chosen.append(name))

    assert client.put("/pack", json={"name": "nothing_here"}).status_code == 503
    assert client.put("/pack", json={"name": "../etc"}).status_code == 422
    assert chosen == []
