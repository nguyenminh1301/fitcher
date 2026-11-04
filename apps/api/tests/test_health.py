from fastapi.testclient import TestClient
import pytest

from app.api import runtime
from app.main import app
from app.screening.screen import Screener
from fakes import FakeClassifier


@pytest.fixture
def health():
    def get(screener=None, failure: Exception | None = None):
        def screener_dependency():
            if failure is not None:
                raise failure
            return screener

        original = runtime.get_screener
        runtime.get_screener = screener_dependency
        try:
            with TestClient(app) as client:
                return client.get("/health")
        finally:
            runtime.get_screener = original

    return get


def test_health_reports_ready_screening_with_the_classifier_version(health):
    response = health(Screener(FakeClassifier()))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "screening": "ready", "classifier": "fake-guard@1"}


def test_health_stays_ok_without_the_classifier(health):
    assert health(Screener(None)).json() == {"status": "ok", "screening": "unavailable", "classifier": None}


def test_health_stays_ok_with_invalid_screening_settings(health):
    response = health(failure=RuntimeError("SCREEN_MODE must be one of log, enforce"))
    assert response.status_code == 200 and response.json()["screening"] == "unavailable"
