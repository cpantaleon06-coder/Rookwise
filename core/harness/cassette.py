"""Record and replay of model calls, inside the harness.

Mode comes from `HARNESS_MODE` (or config/harness.json): `live` (default) calls the
API; `record` calls the API and writes what came back; `replay` reads it back and never
calls the API. On a replay miss, `CassetteMiss` is raised with the key and a hint.

- Key: SHA-256 of the canonical request body (sorted keys, no whitespace, any field
  named like a credential removed), plus a per-key sequence index, so repeated
  identical calls replay in order.
- A cassette stores the normalized deltas (with their time offset), the outcome
  (response id, finish reason, final and running usage) and any error. It stores no
  headers. Before every write it refuses to save anything that contains the API key,
  another secret-looking environment value, or a bearer token.
- Replay goes through the ledger like a live call, so reservations and charges are
  identical. Only the final attempt of a recorded call is stored: a call that needed a
  retry when recorded succeeds at once on replay (same charges, fewer error events).
  Replay is instant unless `realtime=True`, which waits out the recorded offsets.
- Recording starts a fresh cassette file: the first write replaces an existing one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from rookwise.harness.config import Mode
from rookwise.harness.retry import HarnessError

VERSION = 1
# Fields never kept in a key or a cassette, at any depth, compared case-insensitively.
SECRET_FIELDS = frozenset({"authorization", "api_key", "api-key", "x-api-key", "apikey"})
SECRET_PATTERNS = (
    re.compile(r"bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
)
_SECRET_ENV_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.IGNORECASE)


class CassetteMiss(HarnessError):
    """Replay found no recording for this request. Replay never falls back to live."""

    def __init__(self, key: str, index: int, path: Path) -> None:
        super().__init__(
            f"no recording for request key {key} (call {index}) in {path}. Record it with "
            "HARNESS_MODE=record, or check that the request (model, messages, parameters) "
            "is identical to the recorded one."
        )
        self.key = key
        self.index = index


class CassetteSecretError(HarnessError):
    """A cassette write was refused because it would contain a secret."""


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: _strip_secrets(v) for k, v in value.items() if str(k).lower() not in SECRET_FIELDS
        }
    if isinstance(value, list | tuple):
        return [_strip_secrets(v) for v in value]
    return value


def canonical_json(body: Mapping[str, Any]) -> str:
    return json.dumps(
        _strip_secrets(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def request_key(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def env_secrets(environ: Mapping[str, str] | None = None) -> list[str]:
    """Values of environment variables whose names look like credentials."""
    environ = os.environ if environ is None else environ
    return [
        value.strip()
        for name, value in environ.items()
        if _SECRET_ENV_NAME.search(name) and len(value.strip()) >= 8
    ]


def find_secrets(text: str, secrets: Iterable[str] = ()) -> list[str]:
    """Descriptions (never the values) of secret-looking content found in `text`."""
    found = [f"secret value #{i}" for i, s in enumerate(secrets) if s and s in text]
    found += [f"pattern {p.pattern}" for p in SECRET_PATTERNS if p.search(text)]
    lowered = text.lower()
    found += [f'field "{f}"' for f in SECRET_FIELDS if f'"{f}":' in lowered]
    return found


class Cassette:
    """One cassette file. Holds its own sequence counters; never shared between runs."""

    def __init__(
        self,
        path: Path,
        mode: Mode,
        *,
        secrets: Iterable[str] = (),
        realtime: bool = False,
    ) -> None:
        if mode == "live":
            raise ValueError("a cassette is only used in record or replay mode")
        self.path = Path(path)
        self.mode: Mode = mode
        self.realtime = realtime
        self._secrets = [s for s in [*secrets, *env_secrets()] if s]
        self._counters: dict[str, int] = {}
        # Insertion order is call order; replacing a retried attempt keeps its place.
        self._interactions: dict[tuple[str, int], dict[str, Any]] = {}
        if mode == "replay" and self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != VERSION:
                raise HarnessError(f"{self.path}: unsupported cassette version")
            for item in data["interactions"]:
                self._interactions[(item["key"], item["index"])] = item

    def add_secret(self, secret: str) -> None:
        if secret:
            self._secrets.append(secret)

    def next_index(self, key: str) -> int:
        index = self._counters.get(key, 0)
        self._counters[key] = index + 1
        return index

    def lookup(self, key: str, index: int) -> dict[str, Any]:
        try:
            return self._interactions[(key, index)]
        except KeyError:
            raise CassetteMiss(key, index, self.path) from None

    def put(self, interaction: dict[str, Any]) -> None:
        """Store an interaction (replacing an earlier attempt of the same call) and write."""
        interaction = {**interaction, "request": _strip_secrets(interaction["request"])}
        self._interactions[(interaction["key"], interaction["index"])] = interaction
        self._write()

    def _write(self) -> None:
        items = list(self._interactions.values())
        text = json.dumps({"version": VERSION, "interactions": items}, indent=2, ensure_ascii=False)
        problems = find_secrets(text, self._secrets)
        if problems:
            raise CassetteSecretError(
                f"refused to write {self.path}: it would contain {', '.join(problems)}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(text + "\n", encoding="utf-8")
        tmp.replace(self.path)
