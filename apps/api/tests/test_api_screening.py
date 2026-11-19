"""Turning the optional screening classifier on and off over a temporary app state."""

import json

from fastapi.testclient import TestClient
import pytest

from session_fixtures import SessionHeaders
from state_fixtures import new_state

from app.api import runtime, screening as screening_api, setup as setup_api
from app.main import app
from app.screening.screen import Screener
from fakes import FakeClassifier

ADMIN = SessionHeaders(['admin'], user_id='dev.admin')
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
    loaded = []
    screener = Screener(None, loader=lambda: loaded.append(1) or FakeClassifier(), enabled=lambda: False)
    app.dependency_overrides[setup_api.get_state_db] = lambda: db
    app.dependency_overrides[screening_api.get_model_dir] = lambda: model_dir
    app.dependency_overrides[screening_api.get_classifier_screener] = lambda: screener
    app.dependency_overrides[runtime.get_admin_action_log] = lambda: actions
    app.dependency_overrides[screening_api.get_download] = lambda: FakeDownload()
    yield TestClient(app)
    app.dependency_overrides.clear()


def write_model(model_dir):
    model_dir.mkdir()
    for name in ("model.onnx", "tokenizer.json"):
        (model_dir / name).write_bytes(b"x")
    (model_dir / "version.json").write_text(json.dumps({"version": "prompt-guard-2-86m@abc123"}))


def test_the_classifier_starts_off_on_the_provider_engine_with_the_rules_screening_alone(client):
    body = client.get("/screening/classifier", headers=ADMIN).json()

    assert body == {
        "enabled": False, "model_present": False, "version": None, "engine": "provider", "provider_id": None,
        "model": "meta-llama/llama-prompt-guard-2-86m", "download": None,
        "download_source": "gravitee-io/Llama-Prompt-Guard-2-86M-onnx@45a05fb", "license": "Llama 4 Community License",
    }


def test_turning_it_on_without_a_provider_or_a_model_is_refused(client):
    refused = client.post("/screening/classifier", headers=ADMIN)
    local = client.put("/screening/classifier", headers=ADMIN, json={"enabled": True, "engine": "local_onnx"})
    unknown = client.put("/screening/classifier", headers=ADMIN,
                         json={"enabled": True, "engine": "provider", "provider_id": "nope"})

    assert refused.status_code == 422 and "provider" in refused.json()["detail"]
    assert local.status_code == 409 and "Security page" in local.json()["detail"]
    assert unknown.status_code == 422
    assert client.get("/screening/classifier", headers=ADMIN).json()["enabled"] is False


def test_a_model_exported_by_the_job_is_used_when_no_provider_is_named(client, model_dir, actions):
    write_model(model_dir)

    on = client.post("/screening/classifier", headers=ADMIN).json()
    off = client.delete("/screening/classifier", headers=ADMIN).json()

    assert (on["enabled"], on["engine"], on["version"]) == (True, "local_onnx", "prompt-guard-2-86m@abc123")
    assert off["enabled"] is False
    assert [(r.action, r.old_value, r.new_value) for r in actions.records] == [
        ("screening_classifier", "off", "on: this computer"), ("screening_classifier", "on: this computer", "off"),
    ]


def test_the_provider_engine_names_its_provider_and_model_and_reloads_the_screener(client, tmp_path, actions):
    from app.llm.providers import ProviderStore

    db = app.dependency_overrides[setup_api.get_state_db]()
    vault = new_state(tmp_path / "other")[1]
    app.dependency_overrides[screening_api.get_vault] = lambda: vault
    key = "made-up-test-value"
    ProviderStore(db, vault).create("openai_compatible", name="Groq", base_url="https://api.groq.com/openai/v1",
                                    api_key=key)
    body = client.put("/screening/classifier", headers=ADMIN,
                      json={"enabled": True, "engine": "provider", "provider_id": "openai-compatible"}).json()

    assert (body["enabled"], body["engine"], body["provider_id"]) == (True, "provider", "openai-compatible")
    assert body["model"] == "meta-llama/llama-prompt-guard-2-86m"
    assert actions.records[-1].new_value == "on: openai-compatible/meta-llama/llama-prompt-guard-2-86m"


class FakeDownload:
    def __init__(self):
        from app.screening.download import DownloadProgress

        self.progress = DownloadProgress()
        self.calls = []

    @property
    def running(self):
        return self.progress.state == "downloading"

    def start(self):
        self.calls.append("start")
        self.progress.state, self.progress.bytes_done = "downloading", 1024

    def cancel(self):
        self.calls.append("cancel")
        self.progress.state = "cancelled"

    def remove(self):
        self.calls.append("remove")


def test_the_model_download_starts_reports_progress_and_cancels(client):
    download = FakeDownload()
    app.dependency_overrides[screening_api.get_download] = lambda: download

    assert client.get("/screening/classifier/download", headers=ADMIN).json()["state"] == "idle"
    started = client.post("/screening/classifier/download", headers=ADMIN)
    progress = client.get("/screening/classifier", headers=ADMIN).json()["download"]
    cancelled = client.delete("/screening/classifier/download", headers=ADMIN).json()

    assert started.status_code == 202 and started.json()["state"] == "downloading"
    assert progress["bytes_done"] == 1024 and progress["bytes_total"] > 280_000_000
    assert cancelled["state"] == "cancelled" and download.calls == ["start", "cancel"]


def test_a_downloaded_model_is_removed_only_while_the_classifier_does_not_use_it(client, model_dir):
    download = FakeDownload()
    app.dependency_overrides[screening_api.get_download] = lambda: download
    write_model(model_dir)
    client.put("/screening/classifier", headers=ADMIN, json={"enabled": True, "engine": "local_onnx"})

    refused = client.delete("/screening/classifier/download", headers=ADMIN)
    client.delete("/screening/classifier", headers=ADMIN)
    removed = client.delete("/screening/classifier/download", headers=ADMIN)

    assert refused.status_code == 409 and removed.status_code == 200 and download.calls == ["remove"]
