"""Model providers kept in the app state (DECISIONS §2, §9, §15).

A provider has a kind, a unique display name and, for a model server, a base
URL. It may hold several API keys (``provider_keys``); each is a secret in the
vault (``provider:<id>:key:<key id>``, or ``provider:<id>:api_key`` for the key
with id ``legacy`` that was stored before providers had several keys). The
gateway rotates the keys of a provider (``app/llm/key_pool.py``). This store
reports only each key's label and last four characters, and decrypts a key only
to build a ``Route`` for the gateway with a ``SecretReader``.

Hosted kinds (``openai``, ``anthropic``, ``gemini``) need a key and take no
base URL. A model server (``ollama``, ``openai_compatible``) needs an HTTP(S)
base URL; only ``openai_compatible`` takes an optional key. A model server on
the Docker host is reached as ``host.docker.internal`` (DECISIONS §3).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import secrets
from urllib.parse import urlsplit

from app.llm.gateway import Route
from app.state.db import StateDb
from app.state.secrets import SecretReader, SecretVault

KINDS = ("openai", "anthropic", "gemini", "ollama", "openai_compatible")
HOSTED = frozenset({"openai", "anthropic", "gemini"})
DISPLAY_NAMES = {
    "openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Gemini", "ollama": "Ollama",
    "openai_compatible": "OpenAI-compatible",
}
# The LiteLLM model prefix of each kind; a model server's base URL goes with the route. The SDK
# serves Ollama chat as ``ollama_chat`` and Ollama embeddings only as ``ollama``.
SDK_PREFIX = {
    "openai": "openai", "anthropic": "anthropic", "gemini": "gemini", "ollama": "ollama_chat",
    "openai_compatible": "openai",
}
EMBEDDING_PREFIX = {**SDK_PREFIX, "ollama": "ollama"}


class ProviderError(ValueError):
    """The provider's fields do not fit its kind."""


class ProviderNotFound(LookupError):
    pass


@dataclass(frozen=True)
class ProviderKey:
    id: str
    label: str
    last4: str | None
    created_at: str


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    kind: str
    base_url: str | None
    key_set: bool
    # The last four characters of the first key.
    key_last4: str | None
    keys: tuple[ProviderKey, ...] = ()

    @property
    def hosted(self) -> bool:
        return self.kind in HOSTED


LEGACY_KEY_ID = "legacy"


def key_name(provider_id: str, key_id: str = LEGACY_KEY_ID) -> str:
    """The vault secret of one key of the provider."""
    if key_id == LEGACY_KEY_ID:
        return f"provider:{provider_id}:api_key"
    return f"provider:{provider_id}:key:{key_id}"


def _base_url(kind: str, base_url: str | None) -> str | None:
    if kind in HOSTED:
        if base_url:
            raise ProviderError(f"a {kind} provider takes no base URL")
        return None
    if not base_url:
        raise ProviderError(f"a {kind} provider needs a base URL")
    parts = urlsplit(base_url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ProviderError("the base URL must be an http or https address")
    # The base URL is stored and shown in plain text; a key goes through api_key and the vault.
    if parts.username is not None or parts.password is not None:
        raise ProviderError("the base URL must not include user information; enter the key as the API key")
    return base_url.strip().rstrip("/")


def check_fields(kind: str, *, api_key: str | None = None, base_url: str | None = None) -> str | None:
    """Refuse fields that do not fit ``kind``; returns the normalized base URL."""
    if kind not in KINDS:
        raise ProviderError(f"unknown provider kind {kind!r}; use one of {', '.join(KINDS)}")
    if kind in HOSTED and not api_key:
        raise ProviderError(f"a {kind} provider needs an API key")
    if kind == "ollama" and api_key:
        raise ProviderError("an ollama provider takes no API key")
    return _base_url(kind, base_url)


class ProviderStore:
    def __init__(self, db: StateDb, vault: SecretVault):
        self._db = db
        self._vault = vault

    def keys(self, provider_id: str) -> "list[ProviderKey]":
        """The provider's keys, oldest first."""
        rows = self._db.connection().execute(
            "SELECT id, label, created_at FROM provider_keys WHERE provider_id = ? ORDER BY created_at, id",
            (provider_id,),
        ).fetchall()
        return [ProviderKey(key_id, label, self._vault.last_four(key_name(provider_id, key_id)), created)
                for key_id, label, created in rows]

    def _provider(self, row) -> Provider:
        provider_id, name, kind, base_url = row
        keys = tuple(self.keys(provider_id))
        return Provider(provider_id, name, kind, base_url, bool(keys), keys[0].last4 if keys else None, keys)

    def _add_key_in(self, conn, provider_id: str, api_key: str, label: str = "") -> str:
        key_id = secrets.token_hex(4)
        conn.execute(
            "INSERT INTO provider_keys (id, provider_id, label, created_at) VALUES (?, ?, ?, ?)",
            (key_id, provider_id, label.strip()[:60], datetime.now(UTC).isoformat()),
        )
        self._vault.set_in(conn, key_name(provider_id, key_id), api_key)
        return key_id

    def _remove_keys_in(self, conn, provider_id: str) -> None:
        for (key_id,) in conn.execute("SELECT id FROM provider_keys WHERE provider_id = ?", (provider_id,)).fetchall():
            self._vault.delete_in(conn, key_name(provider_id, key_id))
        conn.execute("DELETE FROM provider_keys WHERE provider_id = ?", (provider_id,))

    def add_key(self, provider_id: str, api_key: str, label: str = "") -> ProviderKey:
        """Add a key the gateway rotates with the provider's other keys."""
        provider = self.get(provider_id)
        if provider.kind == "ollama":
            raise ProviderError("an ollama provider takes no API key")
        if not api_key or not api_key.strip():
            raise ProviderError("the key is empty")
        with self._db.write() as conn:
            key_id = self._add_key_in(conn, provider_id, api_key.strip(), label)
        return next(key for key in self.keys(provider_id) if key.id == key_id)

    def remove_key(self, provider_id: str, key_id: str) -> None:
        provider = self.get(provider_id)
        if key_id not in {key.id for key in provider.keys}:
            raise ProviderNotFound(f"provider {provider_id!r} has no key {key_id!r}")
        if provider.kind in HOSTED and len(provider.keys) == 1:
            raise ProviderError(f"a {provider.kind} provider needs an API key; add another key before removing this one")
        with self._db.write() as conn:
            conn.execute("DELETE FROM provider_keys WHERE provider_id = ? AND id = ?", (provider_id, key_id))
            self._vault.delete_in(conn, key_name(provider_id, key_id))

    def list(self) -> list[Provider]:
        rows = self._db.connection().execute(
            "SELECT id, name, kind, base_url FROM providers ORDER BY created_at, id"
        ).fetchall()
        return [self._provider(row) for row in rows]

    def get(self, provider_id: str) -> Provider:
        row = self._db.connection().execute(
            "SELECT id, name, kind, base_url FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        if row is None:
            raise ProviderNotFound(f"no provider {provider_id!r}")
        return self._provider(row)

    def _name_taken(self, name: str, other_than: str | None = None) -> bool:
        row = self._db.connection().execute(
            "SELECT id FROM providers WHERE name = ? AND id IS NOT ?", (name, other_than)
        ).fetchone()
        return row is not None

    def create(self, kind: str, *, name: str | None = None, api_key: str | None = None,
               base_url: str | None = None) -> Provider:
        url = check_fields(kind, api_key=api_key, base_url=base_url)
        name = (name or DISPLAY_NAMES[kind]).strip()
        if not name or self._name_taken(name):
            raise ProviderError(f"the name {name!r} is empty or already used by another provider")
        taken = {row[0] for row in self._db.connection().execute("SELECT id FROM providers").fetchall()}
        provider_id = kind.replace("_", "-")
        number = 1
        while provider_id in taken:
            number += 1
            provider_id = f"{kind.replace('_', '-')}-{number}"
        # The row and its key are written in one transaction: a hosted provider never exists without its key.
        with self._db.write() as conn:
            conn.execute(
                "INSERT INTO providers (id, name, kind, base_url, created_at) VALUES (?, ?, ?, ?, ?)",
                (provider_id, name, kind, url, datetime.now(UTC).isoformat()),
            )
            if api_key:
                self._add_key_in(conn, provider_id, api_key)
        return self.get(provider_id)

    def update(self, provider_id: str, *, name: str | None = None, api_key: str | None = None,
               base_url: str | None = None) -> Provider:
        current = self.get(provider_id)
        if name is not None:
            name = name.strip()
            if not name or self._name_taken(name, provider_id):
                raise ProviderError(f"the name {name!r} is empty or already used by another provider")
        url = _base_url(current.kind, base_url) if base_url is not None else current.base_url
        if api_key and current.kind == "ollama":
            raise ProviderError("an ollama provider takes no API key")
        # The stored key belongs to the address it was entered for: a new address needs its key entered again,
        # so changing the address alone never sends the stored key to it.
        if current.key_set and url != current.base_url and not api_key:
            raise ProviderError("a new base URL needs the provider's API key entered again")
        with self._db.write() as conn:
            conn.execute(
                "UPDATE providers SET name = ?, base_url = ? WHERE id = ?",
                (name if name is not None else current.name, url, provider_id),
            )
            # A replaced key replaces every key: they all belonged to the old address or account.
            if api_key:
                self._remove_keys_in(conn, provider_id)
                self._add_key_in(conn, provider_id, api_key)
        return self.get(provider_id)

    def delete(self, provider_id: str) -> None:
        self.get(provider_id)
        # Removed together, so a provider created later with the same id never finds the old key.
        with self._db.write() as conn:
            self._remove_keys_in(conn, provider_id)
            conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))

    def routes(self, provider_id: str, model: str, reader: SecretReader, *, embedding: bool = False) -> "list[Route]":
        """One route per key of the provider, oldest key first, or one route without a key."""
        provider = self.get(provider_id)
        prefix = (EMBEDDING_PREFIX if embedding else SDK_PREFIX)[provider.kind]
        target = f"{prefix}/{model}"
        if not provider.keys:
            return [Route(provider=provider.id, model=target, api_key=None, api_base=provider.base_url)]
        return [
            Route(provider=provider.id, model=target, api_key=reader.get(key_name(provider_id, key.id)),
                  api_base=provider.base_url, key_id=key.id)
            for key in provider.keys
        ]

    def route(self, provider_id: str, model: str, reader: SecretReader, *, embedding: bool = False) -> Route:
        """Where a chat call, or an ``embedding`` call, to ``model`` of the provider goes, with its first key."""
        return self.routes(provider_id, model, reader, embedding=embedding)[0]
