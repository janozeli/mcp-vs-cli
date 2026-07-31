"""Throwaway probe: how big is a real API response next to the answer it contains?"""

from __future__ import annotations

import json

import httpx

from bench import tokens

BASE = "https://dadosabertos.camara.leg.br/api/v2"

# (label, path, params, projection) — projection is what a `jq` in a CLI pipeline would keep,
# i.e. the smallest thing that still answers a realistic question about that call.
PROBES = [
    (
        "deputies from Sao Paulo",
        "/deputados",
        {"siglaUf": "SP", "itens": 100},
        lambda d: [{"id": x["id"], "nome": x["nome"]} for x in d["dados"]],
    ),
    (
        "bills of one type in a year",
        "/proposicoes",
        {"siglaTipo": "PL", "ano": 2024, "itens": 20},
        lambda d: [{"id": x["id"], "ementa": x.get("ementa", "")[:80]} for x in d["dados"]],
    ),
    (
        "one deputy's expenses",
        "/deputados/204554/despesas",
        {"ano": 2024, "itens": 20},
        lambda d: round(sum(x["valorLiquido"] for x in d["dados"]), 2),
    ),
    (
        "votes in a month",
        "/votacoes",
        {"dataInicio": "2024-03-01", "dataFim": "2024-03-31", "itens": 20},
        lambda d: [x["id"] for x in d["dados"]],
    ),
    (
        "one bill's details",
        "/proposicoes/2390524",
        {},
        lambda d: d["dados"].get("ementa", ""),
    ),
]


def main() -> None:
    client = httpx.Client(timeout=45, headers={"Accept": "application/json"})
    rows = []
    for label, path, params, project in PROBES:
        r = client.get(f"{BASE}{path}", params=params)
        r.raise_for_status()
        body = r.json()
        raw = tokens.count_json(body)
        try:
            projected = tokens.count_json(project(body))
        except Exception as exc:
            projected = -1
            label = f"{label} (projection failed: {exc})"
        rows.append((label, raw, projected))

    print(f"{'call':<34}{'raw':>9}{'projected':>11}{'ratio':>9}")
    for label, raw, projected in rows:
        ratio = f"{raw / projected:.0f}x" if projected > 0 else "-"
        print(f"{label:<34}{raw:>9,}{projected:>11,}{ratio:>9}")
    total_raw = sum(r for _, r, _ in rows)
    total_proj = sum(p for _, _, p in rows if p > 0)
    print(f"\n{'total across 5 calls':<34}{total_raw:>9,}{total_proj:>11,}{total_raw / total_proj:>8.0f}x")
    print(json.dumps({"raw": total_raw, "projected": total_proj}, indent=2))


if __name__ == "__main__":
    main()
