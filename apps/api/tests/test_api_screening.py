"""Turning the optional screening classifier on and off over a temporary app state."""

import json

from fastapi.testclient import TestClient
import pytest

from session_fixtures import SessionHeaders
from state_fixtures import new_state

from app.api import runtime, screening as screening_api, setup as setup_api
from app.main import app
from app.state.settings import Settings
from app.screening.screen import Screener
from fakes import FakeClassifier

ADMIN = SessionHeaders(['admin'], user_id='lab.admin')
VIEWER = SessionHeaders()


class Actions:
    def __init__(self):
        self.records = []

    def record_action(self, record) -> None:
        self.records.append(record)


@pytest.fixture
def model_dir(tmp_path):
    return tmp_path / "guard_model"


@pytest.fixture
def actions():
    return Actions()


@pytest.fixture
def client(tmp_path, model_dir, actions):
    db, _ = new_state(tmp_path)
    Settings(db).set("instance", "mode", "team")
    loaded = []
    screener = Screener(None, loader=lambda: loaded.append(1) or FakeClassifier(), enabled=lambda: False)
    app.dependency_overrides[setup_api.get_state_db] = lambda: db
    app.dependency_overrides[screening_api.get_model_dir] = lambda: model_dir
    app.dependency_overrides[screening_api.get_classifier_screener] = lambda: screener
    app.dependency_overrides[runtime.get_admin_action_log] = lambda: actions
    yield TestClient(app)
    app.dependency_overrides.clear()


def write_model(model_dir):
    model_dir.mkdir()
    for name in ("model.onnx", "tokenizer.json"):
        (model_dir / name).write_bytes(b"x")
    (model_dir / "version.json").write_text(json.dumps({"version": "prompt-guard-2-86m@abc123"}))


@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_only_an_admin_reaches_the_classifier(client, method):
    assert getattr(client, method)("/screening/classifier", headers=VIEWER).status_code == 403


def test_the_classifier_starts_off_with_the_rules_screening_alone(client):
    assert client.get("/screening/classifier", headers=ADMIN).json() == {
        "enabled": False, "model_present": False, "version": None,
    }


def test_turning_it_on_without_its_model_says_how_to_fetch_it(client):
    refused = client.post("/screening/classifier", headers=ADMIN)

    assert refused.status_code == 409 and "guard-model" in refused.json()["detail"]
    assert client.get("/screening/classifier", headers=ADMIN).json()["enabled"] is False


def test_turning_it_on_and_off_is_stored_and_recorded(client, model_dir, actions):
    write_model(model_dir)

    on = client.post("/screening/classifier", headers=ADMIN).json()
    off = client.delete("/screening/classifier", headers=ADMIN).json()

    assert on == {"enabled": True, "model_present": True, "version": "prompt-guard-2-86m@abc123"}
    assert off["enabled"] is False
    assert [(r.action, r.old_value, r.new_value) for r in actions.records] == [
        ("screening_classifier", "off", "on"), ("screening_classifier", "on", "off"),
    ]
