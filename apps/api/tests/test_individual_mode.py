"""Individual mode: one owner without sign-in, reachable only through allowed hosts and same-origin changes."""

from ipaddress import ip_address

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture

from app.api import runtime
from app.auth import origin, owner
from app.main import app
from app.state.db import shared_state

PACK_ROLES = [role.id for role in compiled_fixture().pack.policies.roles]
pytestmark = pytest.mark.address_checks
PASSWORD = "correct horse battery"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FITCHER_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("FITCHER_INTERNAL_HOSTS", raising=False)
    monkeypatch.delenv("FITCHER_TRUSTED_PEERS", raising=False)
    monkeypatch.setattr(origin, "default_gateways", lambda: frozenset({ip_address("172.17.0.1")}))
    app.dependency_overrides[runtime.get_compiled] = compiled_fixture
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    with TestClient(app, base_url="http://localhost:3000", client=("127.0.0.1", 50000)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_every_request_acts_as_the_owner_with_every_role(client):
    response = client.get("/me")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "owner", "display_name": "Owner", "roles": [*PACK_ROLES, "pack_reviewer", "admin"],
        "active_role": PACK_ROLES[0], "exposed": False,
    }


@pytest.mark.parametrize("host", ["localhost", "localhost:3000", "127.0.0.1:8000", "[::1]:3000"])
def test_loopback_hosts_are_accepted(client, host):
    assert client.get("/me", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["example.com", "evil.localhost.example", "10.0.0.5:3000", ""])
def test_a_foreign_host_is_refused(client, host):
    response = client.get("/me", headers={"Host": host})

    assert response.status_code == 403
    assert "FITCHER_ALLOWED_HOSTS" in response.json()["detail"]


def test_an_allowed_host_passes_the_address_check_and_is_reported_as_exposed(client, monkeypatch):
    monkeypatch.setenv("FITCHER_ALLOWED_HOSTS", "fitcher.lan, 192.168.1.20")
    owner.set_password(shared_state(), PASSWORD)
    client.post("/owner/session", json={"password": PASSWORD}, headers={"Origin": "http://localhost:3000"})

    response = client.get("/me", headers={"Host": "fitcher.lan:3000"})

    assert response.status_code == 200
    assert response.json()["exposed"] is True
    assert client.get("/me", headers={"Host": "192.168.1.20"}).status_code == 200


def test_an_internal_host_is_accepted_without_exposing_the_instance(client, monkeypatch):
    monkeypatch.setenv("FITCHER_INTERNAL_HOSTS", "api")

    response = client.get("/me", headers={"Host": "api:8000"})

    assert response.status_code == 200
    assert response.json()["exposed"] is False


def test_a_forwarded_host_must_be_allowed_too(client, monkeypatch):
    monkeypatch.setenv("FITCHER_INTERNAL_HOSTS", "api")

    assert client.get("/me", headers={"Host": "api:8000", "X-Forwarded-Host": "localhost:3000"}).status_code == 200
    assert client.get("/me", headers={"Host": "api:8000", "X-Forwarded-Host": "example.com"}).status_code == 403


@pytest.mark.parametrize("headers", [
    {},
    {"Origin": "http://example.com"},
    {"Origin": "http://localhost:3001"},
    {"Origin": "null"},
])
def test_a_change_without_the_same_origin_is_refused(client, headers):
    response = client.post("/setup/steps/models/skip", headers=headers)

    assert response.status_code == 403


def test_a_change_from_the_same_origin_is_accepted(client):
    assert client.post("/setup/steps/models/skip", headers={"Origin": "http://localhost:3000"}).status_code == 200


def test_a_change_forwarded_by_the_web_server_compares_the_browser_origin(client, monkeypatch):
    monkeypatch.setenv("FITCHER_INTERNAL_HOSTS", "api")
    forwarded = {"Host": "api:8000", "X-Forwarded-Host": "localhost:3000"}

    assert client.post("/setup/steps/models/skip", headers={**forwarded, "Origin": "http://localhost:3000"}).status_code == 200
    assert client.post("/setup/steps/models/skip", headers={**forwarded, "Origin": "http://api:8000"}).status_code == 403


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "::ffff:127.0.0.1", "172.17.0.1", "::ffff:172.17.0.1"])
def test_a_loopback_host_from_this_computer_is_accepted(client, peer):
    assert client.get("/me", headers={"X-Fitcher-Peer": peer}).status_code == 200


@pytest.mark.parametrize("peer", ["172.17.0.9", "192.168.1.50", "::ffff:10.0.0.4", "2001:db8::7", "not-an-address", ""])
def test_a_loopback_host_claimed_by_another_machine_is_refused(client, peer):
    response = client.get("/me", headers={"Host": "localhost:3000", "X-Fitcher-Peer": peer})

    assert response.status_code == 403
    assert "FITCHER_TRUSTED_PEERS" in response.json()["detail"]


@pytest.mark.parametrize("evidence", ["x-forwarded-for", "via", "connection: close", "http/1.0"])
def test_a_loopback_host_relayed_by_a_proxy_on_this_computer_is_refused(client, evidence):
    proxied = {"X-Forwarded-Host": "127.0.0.1:3002", "X-Fitcher-Peer": "172.17.0.1", "X-Fitcher-Proxy": evidence}

    session = client.get("/me", headers=proxied)
    password = client.put("/owner/password", json={"new_password": "attacker-owns-this"},
                          headers={**proxied, "Origin": "http://127.0.0.1:3002"})

    assert session.status_code == 403 and "reverse proxy" in session.json()["detail"]
    assert password.status_code == 403
    assert client.get("/owner/status").json()["password_set"] is False


def test_a_request_without_proxy_evidence_from_the_gateway_is_still_this_computer(client):
    local = {"X-Forwarded-Host": "localhost:3000", "X-Fitcher-Peer": "172.17.0.1", "X-Fitcher-Proxy": ""}

    assert client.get("/me", headers=local).status_code == 200
    assert client.put("/owner/password", json={"new_password": PASSWORD},
                      headers={**local, "Origin": "http://localhost:3000"}).status_code == 204


def test_a_proxy_that_sends_an_allowed_public_name_reaches_the_owner_password(client, monkeypatch):
    monkeypatch.setenv("FITCHER_ALLOWED_HOSTS", "fitcher.example.com")
    proxied = {"X-Forwarded-Host": "fitcher.example.com", "X-Fitcher-Peer": "172.17.0.1",
               "X-Fitcher-Proxy": "x-forwarded-for, connection: close"}

    assert client.get("/me", headers=proxied).status_code == 403
    assert client.get("/owner/status", headers=proxied).json()["password_set"] is False
    owner.set_password(shared_state(), PASSWORD)
    assert client.get("/me", headers=proxied).status_code == 401


def test_a_loopback_host_behind_an_internal_forwarded_host_still_needs_a_local_peer(client, monkeypatch):
    monkeypatch.setenv("FITCHER_INTERNAL_HOSTS", "api")
    headers = {"Host": "localhost:8000", "X-Forwarded-Host": "api:8000", "X-Fitcher-Peer": "172.17.0.9"}

    assert client.get("/me", headers=headers).status_code == 403
    assert client.get("/me", headers={**headers, "X-Fitcher-Peer": "127.0.0.1"}).status_code == 200


def test_without_a_forwarded_peer_the_connection_address_decides(monkeypatch):
    monkeypatch.delenv("FITCHER_TRUSTED_PEERS", raising=False)
    monkeypatch.setattr(origin, "default_gateways", lambda: frozenset())
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    try:
        with TestClient(app, base_url="http://localhost:3000", client=("172.18.0.5", 40000)) as remote:
            assert remote.get("/me").status_code == 403
            assert remote.post("/setup/steps/models/skip", headers={"Origin": "http://localhost:3000"}).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_a_trusted_peer_network_is_accepted(client, monkeypatch):
    monkeypatch.setenv("FITCHER_TRUSTED_PEERS", "10.0.2.0/24, fd00::1")

    assert client.get("/me", headers={"X-Fitcher-Peer": "10.0.2.100"}).status_code == 200
    assert client.get("/me", headers={"X-Fitcher-Peer": "fd00::1"}).status_code == 200
    assert client.get("/me", headers={"X-Fitcher-Peer": "10.0.3.1"}).status_code == 403


def test_an_allowed_host_is_reached_from_other_machines_only_with_the_owner_password(client, monkeypatch):
    monkeypatch.setenv("FITCHER_ALLOWED_HOSTS", "fitcher.lan")
    remote = {"Host": "fitcher.lan", "X-Fitcher-Peer": "192.168.1.50"}

    assert client.get("/me", headers=remote).status_code == 403
    owner.set_password(shared_state(), PASSWORD)
    assert client.get("/me", headers=remote).status_code == 401
    client.post("/owner/session", json={"password": PASSWORD}, headers={**remote, "Origin": "http://fitcher.lan"})
    assert client.get("/me", headers=remote).status_code == 200


def test_the_default_gateway_is_read_from_the_route_table(tmp_path):
    table = tmp_path / "route"
    table.write_text(
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
        "eth0\t00000000\t010011AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
        "eth0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"
        "eth1\t00000000\t010013AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
    )

    assert origin.default_gateways.__wrapped__(table) == frozenset({ip_address("172.17.0.1"), ip_address("172.19.0.1")})
    assert origin.default_gateways.__wrapped__(tmp_path / "missing") == frozenset()
