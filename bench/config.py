"""Where the harness talks to, and as whom."""

from __future__ import annotations

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
API_KEY_ENV = "OPENROUTER_API_KEY"

# Pinned rather than routed: `openrouter/auto` and `openrouter/free` choose a model per request, so
# two cells could run on different models and the comparison would stop being about exposure.
#
# Two tiers of one family, so that a difference between them is capacity rather than vendor. If the
# cost of carrying context hurts the smaller model more, that is a finding in itself.
LARGE_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"  # 1M context
SMALL_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"  # 262k context

MODELS = (LARGE_MODEL, SMALL_MODEL)
MODEL = LARGE_MODEL

# Sampling is fixed across every cell and every trial. Nothing about the comparison should depend on
# the die roll.
TEMPERATURE = 0.0
