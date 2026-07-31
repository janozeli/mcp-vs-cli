"""Five questions about a live API, from trivial to genuinely hard.

Every task carries a solver that computes its answer from the API in the same window as the trial it
grades. Nothing is frozen, so nothing can go quietly stale: what "correct" means is whatever the API
said during this run.

`answer` is the value last observed. It is no longer the grading key — it is a drift signal, checked
by `scripts/check_ground_truth.py`, and the fallback when a caller has not solved live.

The difficulty gradient is deliberate. A one-call lookup and a four-hop aggregation stress completely
different things — the cheap task says whether an arm works at all, the expensive one says what the
arm costs when the work is real.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bench.api import Api

Solver = Callable[[Api], Any]


def _normalise(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _numbers(text: str) -> list[float]:
    """Every number in a piece of text, tolerating both 46,960.46 and 46.960,46."""
    out: list[float] = []
    for raw in re.findall(r"-?\d[\d.,]*", text):
        cleaned = raw.rstrip(".,")
        if "," in cleaned and "." in cleaned:
            # whichever separator comes last is the decimal one
            decimal = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
            thousands = "." if decimal == "," else ","
            cleaned = cleaned.replace(thousands, "").replace(decimal, ".")
        elif "," in cleaned:
            cleaned = (
                cleaned.replace(",", ".") if len(cleaned.split(",")[-1]) != 3 else cleaned.replace(",", "")
            )
        try:
            out.append(float(cleaned))
        except ValueError:
            continue
    return out


@dataclass(frozen=True, slots=True)
class Task:
    """One question, a solver that answers it live, and the operations needed to reach it."""

    id: str
    difficulty: int
    question: str
    requires: tuple[str, ...]

    answer: str | float
    """The value last observed. A drift reference, not the grading key."""

    solver: Solver
    why_this_hard: str
    tolerance: float = 0.0
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_numeric(self) -> bool:
        return isinstance(self.answer, (int, float)) and not isinstance(self.answer, bool)

    def check(self, response: str, expected: str | float | None = None) -> bool:
        """Grade a free-text response against what the API said, falling back to the last known value.

        Deliberately not an LLM judge. Models are asked for the value alone, so this looks for the
        value: a numeric answer must appear as a number, a textual one as a substring. The failure
        mode is a false positive when a model pads its reply with unrelated figures, which is why the
        prompt asks for the final value only.
        """
        target_value = self.answer if expected is None else expected
        if isinstance(target_value, (int, float)) and not isinstance(target_value, bool):
            target = float(target_value)
            return any(abs(n - target) <= self.tolerance for n in _numbers(response))
        candidates = (str(target_value), *self.aliases)
        haystack = _normalise(response)
        return any(_normalise(c) in haystack for c in candidates)


# --- solvers ------------------------------------------------------------------------------------
# Each one makes exactly the calls a correct agent would have to make, against the same live API the
# trial is about to use.


def _solve_deputy_civil_name(api: Api) -> str:
    body = api.get("/deputados/204554").body
    return str(body["dados"]["nomeCivil"])


def _solve_acre_headcount(api: Api) -> int:
    body = api.get("/deputados", {"siglaUf": "AC", "itens": 100}).body
    return len(body["dados"])


def _solve_march_expenses(api: Api) -> float:
    found = api.get("/deputados", {"nome": "Socorro Neri", "siglaUf": "AC"}).body
    deputy_id = found["dados"][0]["id"]
    # 24 records against a default page size of 15: the total is only right if the agent noticed.
    body = api.get(f"/deputados/{deputy_id}/despesas", {"ano": 2024, "mes": 3, "itens": 100}).body
    return round(sum(float(item["valorLiquido"]) for item in body["dados"]), 2)


def _solve_sao_paulo_yes_votes(api: Api) -> int:
    body = api.get("/votacoes/2400758-37/votos").body
    return sum(1 for v in body["dados"] if v["tipoVoto"] == "Sim" and v["deputado_"]["siglaUf"] == "SP")


def _solve_session_party_with_most_no_votes(api: Api) -> str:
    votacao = api.get("/votacoes/2400758-37").body["dados"]
    event_id = votacao["idEvento"]
    siblings = api.get(f"/eventos/{event_id}/votacoes").body["dados"]
    tally: Counter[str] = Counter()
    for sibling in siblings:
        votes = api.get(f"/votacoes/{sibling['id']}/votos").body.get("dados") or []
        for vote in votes:
            if vote["tipoVoto"] == "Não":
                tally[vote["deputado_"]["siglaPartido"]] += 1
    return tally.most_common(1)[0][0]


TASKS: tuple[Task, ...] = (
    Task(
        id="t1-civil-name",
        difficulty=1,
        question="What is the civil name (nomeCivil) of the deputy whose id is 204554?",
        requires=("get_deputados",),
        answer="JOSE ABILIO SILVA DE SANTANA",
        solver=_solve_deputy_civil_name,
        why_this_hard=(
            "It is not. One call, one field, no filtering. This is the floor: an arm that cannot do "
            "this is broken, and the cost recorded here is close to the cost of the exposure itself."
        ),
    ),
    Task(
        id="t2-acre-headcount",
        difficulty=2,
        question="How many deputies currently represent the state of Acre (UF 'AC')?",
        requires=("list_deputados",),
        answer=8,
        solver=_solve_acre_headcount,
        why_this_hard=(
            "One call, but the agent has to find the filter parameter and then count rather than "
            "read. Acre is the smallest delegation, so the payload stays modest on purpose."
        ),
    ),
    Task(
        id="t3-march-expenses",
        difficulty=3,
        question=(
            "What was the total value (valorLiquido) of all expenses filed by deputy Socorro Neri "
            "in March 2024?"
        ),
        requires=("list_deputados", "list_deputados_despesas"),
        answer=46960.46,
        tolerance=0.01,
        solver=_solve_march_expenses,
        why_this_hard=(
            "Two hops — name to id, then expenses — plus a sum. The trap is pagination: there are 24 "
            "records and the default page size is 15, so an agent that does not read the parameters "
            "returns a confidently wrong number."
        ),
    ),
    Task(
        id="t4-sao-paulo-yes-votes",
        difficulty=4,
        question=(
            "In the vote (votação) with id '2400758-37', how many deputies from São Paulo (SP) voted 'Sim'?"
        ),
        requires=("list_votacoes_votos",),
        answer=22,
        solver=_solve_sao_paulo_yes_votes,
        why_this_hard=(
            "One call, and that is the point: the response is 366 nested records and roughly 150 kB. "
            "This is where returning a payload whole stops being free. The endpoint also rejects "
            "`itens` with a 400, so an agent that assumes it can page has to recover."
        ),
    ),
    Task(
        id="t5-session-party-no-votes",
        difficulty=5,
        question=(
            "The vote (votação) with id '2400758-37' was held during a session (evento). Considering "
            "every vote held in that same session, which political party cast the most 'Não' votes "
            "in total?"
        ),
        requires=("get_votacoes", "list_eventos_votacoes", "list_votacoes_votos"),
        answer="PT",
        solver=_solve_session_party_with_most_no_votes,
        why_this_hard=(
            "Four hops with a fan-out and no shortcut: the session id is only on the vote's detail "
            "record, its sibling votes have to be listed, and each one's ballot fetched. Two of the "
            "three return no nominal votes, so the agent has to tell an empty result from a failure."
        ),
    ),
)


def by_id(task_id: str) -> Task:
    for task in TASKS:
        if task.id == task_id:
            return task
    raise KeyError(f"unknown task: {task_id!r}")


def required_operations() -> tuple[str, ...]:
    """Every operation the suite depends on — what `Registry.sample(keep=...)` must preserve."""
    names: list[str] = []
    for task in TASKS:
        names.extend(name for name in task.requires if name not in names)
    return tuple(names)
