"""The one way this benchmark reaches the API: live, every time, storing nothing.

There is no cache and no recorded corpus. A trial sees the API as it is at the moment it runs, which
is the same thing an agent in the wild sees. The cost of that choice is deliberate and is stated in
the README rather than engineered away: two arms answering the same question can, in principle,
receive different data, and a third party cannot re-execute a past run.

What replaces the guarantee is measurement. Every response is written to the trial's trace verbatim,
so a comparison can be checked *after the fact* for whether its arms actually saw the same bytes —
`scripts/verify_parity.py`. Detecting the problem is honest; pretending a frozen corpus made it
impossible was only true inside the freezer.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

# Pinned so the arms cannot differ by content negotiation.
HEADERS = {"Accept": "application/json"}

# The subject is a public, unauthenticated service run at public expense. Retries are bounded and
# spaced, and nothing here runs concurrently.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
BACKOFF_SECONDS = (1, 3, 8)


@dataclass(frozen=True, slots=True)
class Response:
    """One API response, exactly as it arrived."""

    status: int
    body: Any
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def canonical_request(method: str, path: str, params: Mapping[str, Any] | None) -> str:
    """A stable text form of a request.

    Not used for storage — nothing is stored. It exists so a trace can be read, and so parity
    between two arms can be checked on requests that mean the same thing regardless of the order or
    the types the caller happened to use.
    """
    items = sorted((str(k), str(v)) for k, v in (params or {}).items())
    query = "&".join(f"{k}={v}" for k, v in items)
    return f"{method.upper()} {path}" + (f"?{query}" if query else "")


class Api:
    """A thin live GET client. Holds a connection, never a response."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        pause: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.calls = 0
        self._pause = pause
        self._client = client or httpx.Client(timeout=timeout, headers=HEADERS)

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Response:
        """Perform one GET, returning whatever came back.

        An error response is a result, not an exception: the API rejecting a parameter is part of
        what the agent has to deal with, and half of what one task measures.
        """
        if self._pause:
            time.sleep(self._pause)
        url = f"{self.base_url}{path}"
        last: httpx.Response | None = None
        for attempt, wait in enumerate((0, *BACKOFF_SECONDS)):
            if wait:
                time.sleep(wait)
            self.calls += 1
            last = self._client.get(url, params=dict(params or {}))
            if last.status_code not in RETRY_STATUSES:
                break
            if attempt == len(BACKOFF_SECONDS):
                break

        assert last is not None
        try:
            body: Any = last.json()
        except ValueError:
            body = {"_non_json_body": last.text}
        return Response(status=last.status_code, body=body, url=str(last.request.url))
