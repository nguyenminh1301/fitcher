"""The signing keys of an OpenID Connect provider, read from its JWKS (DECISIONS §9).

``app/auth/oidc.py`` checks ID tokens with these keys. The JWKS is fetched
once and cached; a key id the cache does not know refreshes it, at most once
per ``min_refresh_seconds``, so a stream of forged key ids cannot hammer the
provider.
"""

from collections.abc import Callable
import threading
import time

import httpx
import jwt


FETCH_TIMEOUT_SECONDS = 5.0


class AuthError(Exception):
    """The token is missing, malformed or fails a check; the request is unauthorized."""


class AuthUnavailable(Exception):
    """The keys cannot be read, so no token can be checked."""


def fetch_json(url: str) -> dict:
    response = httpx.get(url, timeout=FETCH_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


class JwksCache:
    def __init__(
        self, url: str, fetch: Callable[[str], dict] = fetch_json, *,
        min_refresh_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic,
    ):
        self._url = url
        self._fetch = fetch
        self._min_refresh = min_refresh_seconds
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        try:
            document = self._fetch(self._url)
        except Exception as error:  # noqa: BLE001 - any fetch failure leaves no key to check with
            raise AuthUnavailable(f"cannot read the JWKS: {type(error).__name__}") from error
        self._fetched_at = self._clock()
        keys = {}
        for item in document.get("keys", []):
            if item.get("kid") and item.get("use", "sig") == "sig":
                try:
                    keys[item["kid"]] = jwt.PyJWK(item)
                except jwt.PyJWKError:
                    continue
        self._keys = keys

    def key(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            if kid not in self._keys:
                due = self._fetched_at is None or self._clock() - self._fetched_at >= self._min_refresh
                if due:
                    self._refresh()
            if kid not in self._keys:
                raise AuthError(f"no signing key {kid!r} in the JWKS")
            return self._keys[kid]
