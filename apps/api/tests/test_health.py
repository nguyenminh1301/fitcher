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
