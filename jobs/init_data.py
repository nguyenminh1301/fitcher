"""Prepare the data volume and the ClickHouse files before the services of the release image start.

The image's ``init-data`` service runs ``python -m jobs.init_data`` on every start (DECISIONS §3):

- creates the layout under ``FITCHER_DATA_DIR`` (``/data``);
- generates the instance secret key once, unless ``FITCHER_SECRET_KEY`` is supplied;
- generates every ClickHouse user password once into ``secrets/clickhouse.env`` (mode 0600); a password set in
  the environment wins and is not stored, which is how an external server's passwords are supplied;
- writes ``secrets/api.env``, the environment of the long-running services, which never holds the ClickHouse
  admin password, and ``secrets/admin.env``, which adds it for ``migrate`` and the job modules;
- unless ``CLICKHOUSE_URL`` names an external server, renders the embedded server's configuration under
  ``<run dir>/clickhouse``: the users of ``infra/clickhouse/users.d`` and the admin user with password hashes in
  place of ``from_env``, and a low-memory profile sized from the container's memory limit.

The rendered configuration is rebuilt on every start, so a new memory limit takes effect on the next start.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import sys
from urllib.parse import urlsplit

from app.state.secrets import derive_key, load_key

ADMIN_USER = "fitcher_admin"
ADMIN_PASSWORD = "CLICKHOUSE_ADMIN_PASSWORD"
# Passwords of the ClickHouse users (infra/clickhouse/users.d, infra/image/clickhouse/users.d) and the secret from
# which compile_pack derives the pack's per-role user passwords.
PASSWORD_SETTINGS = (
    ADMIN_PASSWORD,
    "CLICKHOUSE_AGENT_PASSWORD",
    "CLICKHOUSE_LOGS_WRITER_PASSWORD",
    "CLICKHOUSE_TRACE_READER_PASSWORD",
    "CLICKHOUSE_REVIEW_READER_PASSWORD",
    "CLICKHOUSE_QUERY_STOPPER_PASSWORD",
    "CLICKHOUSE_CONVERSATIONS_PASSWORD",
    "CLICKHOUSE_MODEL_TIERS_PASSWORD",
    "CLICKHOUSE_PACK_REVIEW_PASSWORD",
    "CLICKHOUSE_SOURCES_PASSWORD",
    # The api creates and drops the named collections of the sources connected on the Sources page.
    "CLICKHOUSE_SOURCE_ADMIN_PASSWORD",
)
# Needed only by migrate and the jobs that manage ClickHouse users or copy sources.
ADMIN_ONLY = frozenset({ADMIN_PASSWORD, "CLICKHOUSE_SOURCES_PASSWORD"})
# ClickHouse stores the named collections of connected sources encrypted with a key derived from the instance key.
COLLECTIONS_KEY_PURPOSE = "clickhouse named collections"
DATA_DIRS = ("clickhouse", "clickhouse/tmp", "packs", "compiled", "documents", "models", "models/guard", "qdrant", "secrets")
PASSWORDS_FILE = "clickhouse.env"
EMBEDDED_HOST = "127.0.0.1"
HTTP_PORT = 8123

# The embedded server takes this share of the container's memory, never less than the floor; one agent query
# gets half of the server's cap and at most the engine default (app.data.clickhouse.QueryLimits).
SERVER_MEMORY_SHARE = 0.5
SERVER_MEMORY_FLOOR = 768 * 1024**2
QUERY_MEMORY_DEFAULT = 2_000_000_000
MARK_CACHE_BYTES = 128 * 1024**2
MAX_QUERY_THREADS = 4
# GROUP BY and ORDER BY spill to tmp_path once they use this share of the query's memory limit.
SPILL_RATIO = 0.5
# System logs that cost memory and disk on a small machine; query_log stays because the console's trace reads it.
DISABLED_SYSTEM_LOGS = (
    "metric_log", "asynchronous_metric_log", "trace_log", "text_log",
    "query_metric_log", "latency_log", "error_log", "processors_profile_log", "query_thread_log", "part_log",
)

_FROM_ENV = re.compile(r'<password\s+from_env="([A-Z0-9_]+)"\s*/>')


class InitError(RuntimeError):
    """The data volume or the environment cannot be prepared."""


@dataclass(frozen=True)
class MemoryProfile:
    server_memory: int
    query_memory: int
    mark_cache: int
    max_threads: int


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def read_env_file(path: Path) -> dict[str, str]:
    """The ``NAME=value`` lines of an env file written by this module (values shell-quoted)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, _, raw = line.partition("=")
        parts = shlex.split(raw)
        values[name.strip()] = parts[0] if parts else ""
    return values


def _env_text(values: Mapping[str, str]) -> str:
    return "".join(f"{name}={shlex.quote(value)}\n" for name, value in values.items())


def ensure_passwords(secrets_dir: Path, env: Mapping[str, str]) -> dict[str, str]:
    """Every ClickHouse password: from the environment, else stored, else generated and stored."""
    path = Path(secrets_dir) / PASSWORDS_FILE
    stored = read_env_file(path)
    kept = {name: stored[name] for name in PASSWORD_SETTINGS if stored.get(name) and not env.get(name)}
    for name in PASSWORD_SETTINGS:
        if not env.get(name) and name not in kept:
            kept[name] = secrets.token_urlsafe(32)
    _write_private(path, _env_text(kept))
    return {name: env.get(name) or kept[name] for name in PASSWORD_SETTINGS}


def render_users(template_dirs: Iterable[Path], out_dir: Path, passwords: Mapping[str, str]) -> None:
    """Copy the users files with each ``<password from_env>`` replaced by the password's SHA-256 hash."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def hashed(match: re.Match) -> str:
        name = match.group(1)
        if name not in passwords:
            raise InitError(f"a ClickHouse users file reads {name}, which is not a generated password")
        digest = hashlib.sha256(passwords[name].encode("utf-8")).hexdigest()
        return f"<password_sha256_hex>{digest}</password_sha256_hex>"

    for directory in template_dirs:
        for template in sorted(Path(directory).glob("*.xml")):
            (out_dir / template.name).write_text(_FROM_ENV.sub(hashed, template.read_text(encoding="utf-8")),
                                                 encoding="utf-8")


def clickhouse_endpoint(env: Mapping[str, str]) -> tuple[str, int, bool]:
    """``(host, http port, embedded)``: the server ``CLICKHOUSE_URL`` names, else the embedded one."""
    url = env.get("CLICKHOUSE_URL", "").strip()
    if not url:
        return EMBEDDED_HOST, HTTP_PORT, True
    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.hostname:
        raise InitError(f"CLICKHOUSE_URL must be http://<host>[:<port>] of the ClickHouse HTTP interface, got {url!r}")
    return parts.hostname, parts.port or HTTP_PORT, False


def _machine_memory(meminfo: Path) -> int | None:
    try:
        for line in Path(meminfo).read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def memory_limit(cgroup: Path = Path("/sys/fs/cgroup"), meminfo: Path = Path("/proc/meminfo")) -> int | None:
    """The container's memory limit from cgroup v2 or v1, else the machine's memory."""
    machine = _machine_memory(meminfo)
    for candidate in (Path(cgroup) / "memory.max", Path(cgroup) / "memory" / "memory.limit_in_bytes"):
        try:
            raw = candidate.read_text(encoding="ascii").strip()
        except OSError:
            continue
        if raw.isdigit() and (machine is None or int(raw) < machine):
            return int(raw)
        break
    return machine


def memory_profile(limit: int | None) -> MemoryProfile:
    server = max(SERVER_MEMORY_FLOOR, int((limit or 0) * SERVER_MEMORY_SHARE))
    query = min(QUERY_MEMORY_DEFAULT, server // 2)
    return MemoryProfile(server_memory=server, query_memory=query, mark_cache=MARK_CACHE_BYTES,
                         max_threads=min(MAX_QUERY_THREADS, os.cpu_count() or 1))


def render_server_config(out_dir: Path, profile: MemoryProfile, data_dir: Path, collections_key: bytes) -> None:
    """The embedded server's overrides: loopback only, paths under the volume, the low-memory profile and the
    encrypted storage of the named collections created with SQL (DECISIONS §4)."""
    out_dir = Path(out_dir)
    clickhouse = f"{Path(data_dir) / 'clickhouse'}/"
    removed = "\n".join(f'    <{name} remove="1"/>' for name in DISABLED_SYSTEM_LOGS)
    config = f"""<clickhouse>
    <!-- Rendered by jobs.init_data on every start of the release image; edits are overwritten. -->
    <listen_host replace="replace">{EMBEDDED_HOST}</listen_host>
    <http_port>{HTTP_PORT}</http_port>
    <tcp_port>9000</tcp_port>
    <interserver_http_port remove="1"/>
    <mysql_port remove="1"/>
    <postgresql_port remove="1"/>
    <path>{clickhouse}</path>
    <tmp_path>{clickhouse}tmp/</tmp_path>
    <user_files_path>{clickhouse}user_files/</user_files_path>
    <format_schema_path>{clickhouse}format_schemas/</format_schema_path>
    <user_directories replace="replace">
        <users_xml><path>users.xml</path></users_xml>
        <local_directory><path>{clickhouse}access/</path></local_directory>
    </user_directories>
    <logger replace="replace">
        <level>warning</level>
        <console>1</console>
    </logger>
    <named_collections_storage>
        <type>local_encrypted</type>
        <path>{clickhouse}named_collections</path>
        <algorithm>aes_256_ctr</algorithm>
        <key_hex>{collections_key.hex()}</key_hex>
    </named_collections_storage>
    <max_server_memory_usage>{profile.server_memory}</max_server_memory_usage>
    <mark_cache_size>{profile.mark_cache}</mark_cache_size>
    <index_mark_cache_size>0</index_mark_cache_size>
    <uncompressed_cache_size>0</uncompressed_cache_size>
{removed}
</clickhouse>
"""
    users = f"""<clickhouse>
    <!-- Rendered by jobs.init_data: the base settings of every session, including the pack's per-role users. -->
    <profiles>
        <default>
            <max_threads>{profile.max_threads}</max_threads>
            <max_bytes_ratio_before_external_group_by>{SPILL_RATIO}</max_bytes_ratio_before_external_group_by>
            <max_bytes_ratio_before_external_sort>{SPILL_RATIO}</max_bytes_ratio_before_external_sort>
        </default>
    </profiles>
</clickhouse>
"""
    (out_dir / "config.d").mkdir(parents=True, exist_ok=True)
    (out_dir / "users.d").mkdir(parents=True, exist_ok=True)
    (out_dir / "config.d" / "fitcher.xml").write_text(config, encoding="utf-8")
    (out_dir / "users.d" / "fitcher_profile.xml").write_text(users, encoding="utf-8")


def write_environment(secrets_dir: Path, passwords: Mapping[str, str], endpoint: tuple[str, int, bool],
                      profile: MemoryProfile, env: Mapping[str, str]) -> None:
    host, port, embedded = endpoint
    services = {
        "CLICKHOUSE_HOST": host,
        "CLICKHOUSE_HTTP_PORT": str(port),
        "QUERY_MAX_MEMORY_USAGE": env.get("QUERY_MAX_MEMORY_USAGE") or str(profile.query_memory),
    }
    services |= {name: passwords[name] for name in PASSWORD_SETTINGS if name not in ADMIN_ONLY}
    # The embedded server defines only ADMIN_USER (infra/image/clickhouse/users.d/admin.xml).
    admin_user = ADMIN_USER if embedded else env.get("CLICKHOUSE_ADMIN_USER") or ADMIN_USER
    admin = services | {"CLICKHOUSE_ADMIN_USER": admin_user}
    admin |= {name: passwords[name] for name in ADMIN_ONLY}
    _write_private(Path(secrets_dir) / "api.env", _env_text(services))
    _write_private(Path(secrets_dir) / "admin.env", _env_text(admin))


def initialize(data_dir: Path, run_dir: Path, env: Mapping[str, str], templates: Iterable[Path],
               cgroup: Path = Path("/sys/fs/cgroup"), meminfo: Path = Path("/proc/meminfo"),
               stock_config: Path | None = None) -> None:
    data_dir, run_dir = Path(data_dir), Path(run_dir)
    for name in DATA_DIRS:
        (data_dir / name).mkdir(parents=True, exist_ok=True)
    os.chmod(data_dir / "secrets", 0o700)
    instance_key = load_key(data_dir, dict(env))
    secrets_dir = data_dir / "secrets"
    passwords = ensure_passwords(secrets_dir, env)
    endpoint = clickhouse_endpoint(env)
    profile = memory_profile(memory_limit(cgroup, meminfo))
    write_environment(secrets_dir, passwords, endpoint, profile, env)
    if not endpoint[2]:
        return
    target = run_dir / "clickhouse"
    if target.exists():
        shutil.rmtree(target)
    if stock_config is not None:
        shutil.copytree(stock_config, target)
    render_users(templates, target / "users.d", passwords)
    render_server_config(target, profile, data_dir, derive_key(instance_key, COLLECTIONS_KEY_PURPOSE))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    templates = [root / "infra" / "clickhouse" / "users.d", root / "infra" / "image" / "clickhouse" / "users.d"]
    try:
        initialize(
            Path(os.environ.get("FITCHER_DATA_DIR") or "/data"),
            Path(os.environ.get("FITCHER_RUN_DIR") or "/run/fitcher"),
            os.environ,
            templates,
            stock_config=Path(os.environ.get("CLICKHOUSE_STOCK_CONFIG") or "/etc/clickhouse-server"),
        )
    except (InitError, OSError, RuntimeError) as error:
        print(f"init-data: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
