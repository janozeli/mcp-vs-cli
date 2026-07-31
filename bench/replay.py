"""Record once against the live API, replay from disk forever after.

Two arms answering the same question must see the same bytes. Against a live API they would not: the
data moves, pagination drifts, and a slow request can time out on one trial and not another. Any
difference the benchmark then reports would be partly noise, and there would be no way to tell how
much.

So the corpus is frozen. `record` mode is run deliberately, by a human, to fill the cassette;
everything else runs in `replay` mode, which never touches the network and raises on a miss rather
than silently falling back to it. A run that hits an unrecorded call is a broken run, not a slow one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

Mode = Literal["record", "replay"]

# Pinned so the recorded corpus cannot depend on content negotiation.
HEADERS = {"Accept": "application/json"}


class CassetteMiss(KeyError):
    """A call was requested in replay mode that was never recorded."""


@dataclass(frozen=True, slots=True)
class Recorded:
    """One frozen API response."""

    key: str
    status: int
    body: Any


def canonical_request(method: str, path: str, params: Mapping[str, Any] | None) -> str:
    """A stable text form of a request, so the same call always lands on the same key.

    Parameter order must not matter — an agent that passes `ano` before `itens` is making the same
    call as one that passes them the other way round, and charging it a cache miss would make the
    corpus depend on incidental ordering.
    """
    items = sorted((str(k), str(v)) for k, v in (params or {}).items())
    query = "&".join(f"{k}={v}" for k, v in items)
    return f"{method.upper()} {path}" + (f"?{query}" if query else "")


def key_for(method: str, path: str, params: Mapping[str, Any] | None) -> str:
    digest = hashlib.sha256(canonical_request(method, path, params).encode("utf-8")).hexdigest()
    return digest[:16]


class Cassette:
    """A directory of frozen responses, addressed by request."""

    def __init__(
        self,
        directory: Path | str,
        *,
        base_url: str,
        mode: Mode = "replay",
        client: httpx.Client | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self._client = client
        self.hits = 0
        self.recorded = 0

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def keys(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.json"))

    def __len__(self) -> int:
        return len(self.keys())

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Recorded:
        key = key_for("GET", path, params)
        stored = self._path(key)
        if stored.exists():
            payload = json.loads(stored.read_text(encoding="utf-8"))
            self.hits += 1
            return Recorded(key=key, status=payload["response"]["status"], body=payload["response"]["body"])

        if self.mode != "record":
            raise CassetteMiss(
                f"{canonical_request('GET', path, params)} is not in the cassette at "
                f"{self.directory}. Re-record the corpus instead of running against the live API."
            )
        return self._record(key, path, params)

    def _record(self, key: str, path: str, params: Mapping[str, Any] | None) -> Recorded:
        client = self._client or httpx.Client(timeout=60, headers=HEADERS)
        response = client.get(f"{self.base_url}{path}", params=dict(params or {}))
        response.raise_for_status()
        body = response.json()

        self.directory.mkdir(parents=True, exist_ok=True)
        document = {
            "request": {
                "method": "GET",
                "path": path,
                "params": {str(k): str(v) for k, v in sorted((params or {}).items())},
                "canonical": canonical_request("GET", path, params),
            },
            "response": {"status": response.status_code, "body": body},
            "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._path(key).write_text(
            json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.recorded += 1
        return Recorded(key=key, status=response.status_code, body=body)
