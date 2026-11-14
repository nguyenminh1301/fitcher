"""First start of the release image: data layout, generated secrets, ClickHouse files and the memory profile."""

import hashlib
import os
from pathlib import Path
import stat
import xml.etree.ElementTree as ElementTree

import pytest

from app.state.secrets import derive_key, load_key
from jobs import init_data
from jobs.init_data import (
    COLLECTIONS_KEY_PURPOSE,
    ADMIN_PASSWORD,
    ADMIN_USER,
    PASSWORD_SETTINGS,
    InitError,
    MemoryProfile,
    clickhouse_endpoint,
    ensure_passwords,
    memory_limit,
    memory_profile,
    read_env_file,
    render_server_config,
    render_users,
    write_environment,
)

REPO = Path(__file__).resolve().parents[2]
USER_TEMPLATES = [REPO / "infra" / "clickhouse" / "users.d", REPO / "infra" / "image" / "clickhouse" / "users.d"]
GIB = 1024**3


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# Generated passwords


def test_first_start_generates_every_password_into_a_private_file(tmp_path):
    passwords = ensure_passwords(tmp_path, env={})

    assert set(passwords) == set(PASSWORD_SETTINGS)
    assert all(len(value) >= 32 for value in passwords.values())
    assert len(set(passwords.values())) == len(passwords)
    assert _mode(tmp_path / "clickhouse.env") == 0o600


def test_a_later_start_keeps_the_generated_passwords(tmp_path):
    first = ensure_passwords(tmp_path, env={})

    assert ensure_passwords(tmp_path, env={}) == first


def test_a_password_from_the_environment_wins_and_is_not_stored(tmp_path):
    passwords = ensure_passwords(tmp_path, env={ADMIN_PASSWORD: "from-the-operator"})

    assert passwords[ADMIN_PASSWORD] == "from-the-operator"
    assert "from-the-operator" not in (tmp_path / "clickhouse.env").read_text()


def test_a_password_added_by_a_newer_image_is_generated_without_changing_the_others(tmp_path):
    first = ensure_passwords(tmp_path, env={})
    stored = read_env_file(tmp_path / "clickhouse.env")
    del stored["CLICKHOUSE_SOURCES_PASSWORD"]
    (tmp_path / "clickhouse.env").write_text("".join(f"{k}={v}\n" for k, v in stored.items()))

    second = ensure_passwords(tmp_path, env={})

    assert second["CLICKHOUSE_SOURCES_PASSWORD"] != first["CLICKHOUSE_SOURCES_PASSWORD"]
    assert {k: v for k, v in second.items() if k != "CLICKHOUSE_SOURCES_PASSWORD"} == stored


# Rendered ClickHouse users


def test_rendered_users_hold_password_hashes_and_never_the_passwords(tmp_path):
    passwords = ensure_passwords(tmp_path / "secrets", env={})
    out = tmp_path / "users.d"

    render_users(USER_TEMPLATES, out, passwords)

    text = "".join(path.read_text() for path in out.glob("*.xml"))
    assert "from_env" not in text
    for value in passwords.values():
        assert value not in text
    writer = ElementTree.parse(out / "agent_logs.xml").getroot().find("users/agent_logs_writer")
    expected = hashlib.sha256(passwords["CLICKHOUSE_LOGS_WRITER_PASSWORD"].encode()).hexdigest()
    assert writer.findtext("password_sha256_hex") == expected


def test_the_embedded_server_gets_an_admin_user_that_manages_access(tmp_path):
    passwords = ensure_passwords(tmp_path / "secrets", env={})
    out = tmp_path / "users.d"

    render_users(USER_TEMPLATES, out, passwords)

    admin = ElementTree.parse(out / "admin.xml").getroot().find(f"users/{ADMIN_USER}")
    assert admin.findtext("password_sha256_hex") == hashlib.sha256(passwords[ADMIN_PASSWORD].encode()).hexdigest()
    assert admin.findtext("access_management") == "1"
    assert admin.findtext("networks/ip") == "127.0.0.1"


def test_a_template_naming_an_unknown_password_is_refused(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "odd.xml").write_text('<clickhouse><users><u><password from_env="NOT_A_PASSWORD"/></u></users></clickhouse>')

    with pytest.raises(InitError, match="NOT_A_PASSWORD"):
        render_users([templates], tmp_path / "out", {})


# Embedded or external ClickHouse


def test_without_a_url_the_embedded_server_on_loopback_is_used():
    assert clickhouse_endpoint({}) == ("127.0.0.1", 8123, True)


def test_a_url_points_at_an_external_server():
    assert clickhouse_endpoint({"CLICKHOUSE_URL": "http://clickhouse.internal:8124"}) == ("clickhouse.internal", 8124, False)


def test_an_external_url_without_a_port_uses_the_http_port():
    assert clickhouse_endpoint({"CLICKHOUSE_URL": "http://clickhouse"}) == ("clickhouse", 8123, False)


@pytest.mark.parametrize("url", ["https://clickhouse:8443", "clickhouse:8123", "http://"])
def test_an_unsupported_url_is_refused(url):
    with pytest.raises(InitError, match="CLICKHOUSE_URL"):
        clickhouse_endpoint({"CLICKHOUSE_URL": url})


# Memory limit and profile


def test_the_cgroup_v2_limit_is_read(tmp_path):
    (tmp_path / "memory.max").write_text(f"{4 * GIB}\n")

    assert memory_limit(cgroup=tmp_path, meminfo=tmp_path / "meminfo") == 4 * GIB


def test_an_unlimited_container_falls_back_to_the_machine_memory(tmp_path):
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "meminfo").write_text("MemTotal:       16000000 kB\nMemFree:  1 kB\n")

    assert memory_limit(cgroup=tmp_path, meminfo=tmp_path / "meminfo") == 16_000_000 * 1024


def test_the_cgroup_v1_limit_is_read(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "memory.limit_in_bytes").write_text(f"{2 * GIB}\n")

    assert memory_limit(cgroup=tmp_path, meminfo=tmp_path / "meminfo") == 2 * GIB


def test_a_cgroup_v1_limit_above_the_machine_memory_means_unlimited(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "memory.limit_in_bytes").write_text("9223372036854771712\n")
    (tmp_path / "meminfo").write_text("MemTotal:       8000000 kB\n")

    assert memory_limit(cgroup=tmp_path, meminfo=tmp_path / "meminfo") == 8_000_000 * 1024


def test_a_4g_container_caps_the_server_at_half_and_a_query_below_that():
    profile = memory_profile(4 * GIB)

    assert profile.server_memory == 2 * GIB
    assert profile.query_memory < profile.server_memory


def test_a_small_container_keeps_the_server_floor():
    profile = memory_profile(1 * GIB)

    assert profile.server_memory == init_data.SERVER_MEMORY_FLOOR
    assert profile.query_memory < profile.server_memory


def test_a_large_machine_keeps_the_default_query_limit():
    assert memory_profile(64 * GIB).query_memory == 2_000_000_000


def test_the_server_config_applies_the_low_memory_profile(tmp_path):
    profile = MemoryProfile(server_memory=2 * GIB, query_memory=GIB, mark_cache=128 * 1024**2, max_threads=4)

    render_server_config(tmp_path, profile, data_dir=Path("/data"), collections_key=bytes(32))

    config = ElementTree.parse(tmp_path / "config.d" / "fitcher.xml").getroot()
    assert config.findtext("max_server_memory_usage") == str(2 * GIB)
    assert config.findtext("mark_cache_size") == str(128 * 1024**2)
    assert config.findtext("path") == "/data/clickhouse/"
    assert config.findtext("tmp_path") == "/data/clickhouse/tmp/"
    assert [node.text for node in config.findall("listen_host")] == ["127.0.0.1"]
    for log in ("metric_log", "asynchronous_metric_log", "trace_log", "text_log"):
        assert config.find(log).get("remove") == "1"
    assert config.find("query_log") is None, "the console's trace reader reads system.query_log"

    defaults = ElementTree.parse(tmp_path / "users.d" / "fitcher_profile.xml").getroot().find("profiles/default")
    assert defaults.findtext("max_threads") == "4"
    assert float(defaults.findtext("max_bytes_ratio_before_external_group_by")) > 0
    assert float(defaults.findtext("max_bytes_ratio_before_external_sort")) > 0


def test_source_credentials_are_stored_in_named_collections_encrypted_with_a_derived_key(tmp_path):
    profile = MemoryProfile(server_memory=2 * GIB, query_memory=GIB, mark_cache=128 * 1024**2, max_threads=4)
    instance_key = bytes([5]) * 32

    render_server_config(tmp_path, profile, data_dir=Path("/data"), collections_key=derive_key(instance_key, COLLECTIONS_KEY_PURPOSE))

    config = ElementTree.parse(tmp_path / "config.d" / "fitcher.xml").getroot()
    storage = config.find("named_collections_storage")
    assert storage.findtext("type") == "local_encrypted"
    assert storage.findtext("path") == "/data/clickhouse/named_collections"
    assert storage.findtext("algorithm") == "aes_256_ctr"
    key_hex = storage.findtext("key_hex")
    assert key_hex == derive_key(instance_key, COLLECTIONS_KEY_PURPOSE).hex()
    assert key_hex != instance_key.hex()


def test_the_source_admin_user_is_rendered_with_a_password_hash_and_reaches_the_api(tmp_path):
    passwords = ensure_passwords(tmp_path, env={})
    render_users(USER_TEMPLATES, tmp_path / "users.d", passwords)

    user = ElementTree.parse(tmp_path / "users.d" / "source_admin.xml").getroot().find("users/source_admin")
    digest = hashlib.sha256(passwords["CLICKHOUSE_SOURCE_ADMIN_PASSWORD"].encode()).hexdigest()
    assert user.findtext("password_sha256_hex") == digest
    assert passwords["CLICKHOUSE_SOURCE_ADMIN_PASSWORD"] not in (tmp_path / "users.d" / "source_admin.xml").read_text()

    write_environment(tmp_path, passwords, ("127.0.0.1", 8123, True), memory_profile(4 * GIB), env={})
    assert read_env_file(tmp_path / "api.env")["CLICKHOUSE_SOURCE_ADMIN_PASSWORD"] == passwords[
        "CLICKHOUSE_SOURCE_ADMIN_PASSWORD"]


def test_the_collection_key_follows_the_instance_key_on_every_start(tmp_path):
    data, run = tmp_path / "data", tmp_path / "run"
    kwargs = dict(env={}, templates=USER_TEMPLATES, cgroup=tmp_path, meminfo=tmp_path / "x")
    init_data.initialize(data, run, **kwargs)
    first = ElementTree.parse(run / "clickhouse" / "config.d" / "fitcher.xml").getroot().findtext(
        "named_collections_storage/key_hex")

    init_data.initialize(data, run, **kwargs)

    assert ElementTree.parse(run / "clickhouse" / "config.d" / "fitcher.xml").getroot().findtext(
        "named_collections_storage/key_hex") == first
    assert first == derive_key(load_key(data, {}), COLLECTIONS_KEY_PURPOSE).hex()


# Environment of the services


def test_the_api_environment_never_holds_the_admin_password(tmp_path):
    passwords = ensure_passwords(tmp_path, env={})
    profile = memory_profile(4 * GIB)

    write_environment(tmp_path, passwords, ("127.0.0.1", 8123, True), profile, env={})

    api = read_env_file(tmp_path / "api.env")
    admin = read_env_file(tmp_path / "admin.env")
    assert ADMIN_PASSWORD not in api and passwords[ADMIN_PASSWORD] not in api.values()
    assert api["CLICKHOUSE_LOGS_WRITER_PASSWORD"] == passwords["CLICKHOUSE_LOGS_WRITER_PASSWORD"]
    assert api["CLICKHOUSE_HOST"] == "127.0.0.1" and api["CLICKHOUSE_HTTP_PORT"] == "8123"
    assert api["QUERY_MAX_MEMORY_USAGE"] == str(profile.query_memory)
    assert admin[ADMIN_PASSWORD] == passwords[ADMIN_PASSWORD]
    assert admin["CLICKHOUSE_ADMIN_USER"] == ADMIN_USER
    assert _mode(tmp_path / "api.env") == 0o600 and _mode(tmp_path / "admin.env") == 0o600


def test_an_operator_query_memory_limit_is_kept(tmp_path):
    passwords = ensure_passwords(tmp_path, env={})

    write_environment(tmp_path, passwords, ("ch", 8123, False), memory_profile(4 * GIB),
                      env={"QUERY_MAX_MEMORY_USAGE": "500000000"})

    assert read_env_file(tmp_path / "api.env")["QUERY_MAX_MEMORY_USAGE"] == "500000000"


def test_values_with_shell_characters_survive_the_env_file(tmp_path):
    passwords = dict.fromkeys(PASSWORD_SETTINGS, "it's $HOME `x`")

    write_environment(tmp_path, passwords, ("127.0.0.1", 8123, True), memory_profile(4 * GIB), env={})

    assert read_env_file(tmp_path / "api.env")["CLICKHOUSE_LOGS_WRITER_PASSWORD"] == "it's $HOME `x`"


# The whole first start


def test_first_start_creates_the_layout_and_the_secret_key(tmp_path):
    data, run = tmp_path / "data", tmp_path / "run"
    (tmp_path / "memory.max").write_text(f"{4 * GIB}\n")

    init_data.initialize(data, run, env={}, templates=USER_TEMPLATES, cgroup=tmp_path, meminfo=tmp_path / "x")

    for name in ("clickhouse", "packs", "compiled", "documents", "models", "secrets"):
        assert (data / name).is_dir()
    assert _mode(data / "secrets") == 0o700
    assert _mode(data / "secret.key") == 0o600
    assert (run / "clickhouse" / "users.d" / "admin.xml").is_file()
    assert (run / "clickhouse" / "config.d" / "fitcher.xml").is_file()


def test_a_supplied_secret_key_is_not_written(tmp_path):
    data, run = tmp_path / "data", tmp_path / "run"

    init_data.initialize(data, run, env={"FITCHER_SECRET_KEY": "A" * 43 + "="}, templates=USER_TEMPLATES,
                         cgroup=tmp_path, meminfo=tmp_path / "x")

    assert not (data / "secret.key").exists()


def test_an_external_server_gets_no_embedded_files(tmp_path):
    data, run = tmp_path / "data", tmp_path / "run"

    init_data.initialize(data, run, env={"CLICKHOUSE_URL": "http://ch:8123"}, templates=USER_TEMPLATES,
                         cgroup=tmp_path, meminfo=tmp_path / "x")

    assert not (run / "clickhouse").exists()
    assert read_env_file(data / "secrets" / "api.env")["CLICKHOUSE_HOST"] == "ch"


def test_a_second_start_changes_no_secret(tmp_path):
    data, run = tmp_path / "data", tmp_path / "run"
    kwargs = dict(env={}, templates=USER_TEMPLATES, cgroup=tmp_path, meminfo=tmp_path / "x")
    init_data.initialize(data, run, **kwargs)
    before = {p: p.read_bytes() for p in [data / "secret.key", data / "secrets" / "clickhouse.env"]}

    init_data.initialize(data, run, **kwargs)

    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX")
def test_files_from_an_earlier_start_get_private_modes_again(tmp_path):
    passwords = ensure_passwords(tmp_path, env={})
    os.chmod(tmp_path / "clickhouse.env", 0o644)

    assert ensure_passwords(tmp_path, env={}) == passwords
    assert _mode(tmp_path / "clickhouse.env") == 0o600


def test_an_admin_user_name_applies_only_to_an_external_server(tmp_path):
    passwords = ensure_passwords(tmp_path, env={})
    env = {"CLICKHOUSE_ADMIN_USER": "ops_admin"}

    write_environment(tmp_path, passwords, ("127.0.0.1", 8123, True), memory_profile(4 * GIB), env=env)
    assert read_env_file(tmp_path / "admin.env")["CLICKHOUSE_ADMIN_USER"] == ADMIN_USER

    write_environment(tmp_path, passwords, ("ch", 8123, False), memory_profile(4 * GIB), env=env)
    assert read_env_file(tmp_path / "admin.env")["CLICKHOUSE_ADMIN_USER"] == "ops_admin"
