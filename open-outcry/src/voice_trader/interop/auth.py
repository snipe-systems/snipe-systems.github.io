"""API-key management for the HTTP and WebSocket interfaces.

Keys are generated once and stored as SHA-256 hashes (never plaintext). The
plaintext key is shown exactly once at creation. Enable enforcement by setting
`api.require_auth: true` in config; generate keys with `voice-trader-key create`.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path


class ApiKeyStore:
    def __init__(self, path: str | Path = "config/api_keys.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records = self._load()

    # --- persistence ---------------------------------------------------------

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._records, indent=2))

    # --- operations ----------------------------------------------------------

    def create(self, label: str = "") -> str:
        """Generate a new key. Returns the plaintext key (shown only once)."""
        key = secrets.token_urlsafe(32)
        self._records.append({
            "hash": hashlib.sha256(key.encode()).hexdigest(),
            "prefix": key[:8],
            "label": label or "",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "revoked": False,
        })
        self._save()
        return key

    def verify(self, key: str | None) -> bool:
        if not key:
            return False
        digest = hashlib.sha256(key.encode()).hexdigest()
        return any(r["hash"] == digest and not r.get("revoked", False)
                   for r in self._records)

    def list(self) -> list[dict]:
        """Public view: no hashes, no secrets."""
        return [{"prefix": r.get("prefix", ""), "label": r.get("label", ""),
                 "created": r.get("created", ""), "revoked": r.get("revoked", False)}
                for r in self._records]

    def revoke(self, prefix: str) -> bool:
        for r in self._records:
            if r.get("prefix") == prefix and not r.get("revoked", False):
                r["revoked"] = True
                self._save()
                return True
        return False

    def count(self) -> int:
        return sum(1 for r in self._records if not r.get("revoked", False))


def load_auth(config: dict) -> ApiKeyStore | None:
    """Return an ApiKeyStore if `api.require_auth` is enabled, else None."""
    api = config.get("api", {})
    if not api.get("require_auth", False):
        return None
    store = ApiKeyStore(api.get("key_file", "config/api_keys.json"))
    if store.count() == 0:
        print("WARNING: api.require_auth is true but no keys exist. "
              "Run `voice-trader-key create`.")
    return store
