"""Token counting for the static, offline part of the analysis.

This is a *static estimate*: it prices a payload with a modern BPE without calling anyone. It is the
right tool for "how much does this tools array cost before the run starts", and the wrong tool for
reporting what a run actually consumed — for that the harness records the provider's own usage
numbers from the response, which are authoritative and differ slightly per provider.
"""

from __future__ import annotations

import functools
import json
from typing import Any

import tiktoken

ENCODING = "o200k_base"


@functools.lru_cache(maxsize=1)
def _encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING)


def count_text(text: str) -> int:
    return len(_encoder().encode(text, disallowed_special=()))


def count_json(payload: Any) -> int:
    """Price a JSON payload the way it goes over the wire: compact, UTF-8, no ASCII escaping."""
    return count_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
