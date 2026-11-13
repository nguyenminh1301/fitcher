from fastapi.testclient import TestClient
import pytest

from app.api import runtime
from app.main import app
from app.screening.screen import Screener
from fakes import FakeClassifier


@pytest.fixture
def health(monkeypatch):
    monkeypatch.setattr(runtime, "build_screener_in_background", lambda: None)

    def get(screener):
        monkeypatch.setattr(runtime, "loaded_screener", lambda: screener)
        with TestClient(app) as client:
            return client.get("/health")

    return get


def test_health_reports_ready_screening_with_the_classifier_version(health):
    response = health(Screener(FakeClassifier()))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "screening": "ready", "classifier": "fake-guard@1"}


def test_health_stays_ok_without_the_classifier(health):
    assert health(Screener(None)).json() == {"status": "ok", "screening": "unavailable", "classifier": None}


def test_health_stays_ok_while_the_screener_is_still_loading(health):
    assert health(None).json() == {"status": "ok", "screening": "unavailable", "classifier": None}


def test_health_never_loads_the_classifier(monkeypatch, health):
    def loader():
        raise AssertionError("health must not load the classifier")

    screener = Screener(None, loader=loader, clock=lambda: 10_000.0)
    assert health(screener).json()["screening"] == "unavailable"


def test_health_reports_rules_only_screening_when_the_classifier_is_off(health):
    assert health(Screener(None, enabled=lambda: False)).json() == {
        "status": "ok", "screening": "rules_only", "classifier": None,
    }


def test_importing_the_api_loads_no_onnx_runtime():
    import subprocess
    import sys

    code = "import sys, app.main; print('onnxruntime' in sys.modules, 'fastembed' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    assert out.stdout.strip() == "False False"
