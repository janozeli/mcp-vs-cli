"""Deliberate, human-run operations against the live API and against a run's traces.

Run them as modules (`uv run python -m scripts.pilot`) so the repository root is on the import path
without any script needing to edit `sys.path`.

- `check_ground_truth` — solve every task live and compare with the recorded reference
- `pilot` — run trials
- `summarise` — recompute a run's numbers from its traces alone
- `verify_parity` — check whether the arms of a comparison saw the same bytes
- `probe_payloads` — how much of a response actually carries the answer
"""
