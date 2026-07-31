/**
 * Five questions about a live API, from trivial to genuinely hard.
 *
 * Every task carries a solver that computes its answer from the API in the same window as the trial
 * it grades. Nothing is frozen, so nothing can go quietly stale: what "correct" means is whatever
 * the API said during this run.
 *
 * `reference` is the value last observed. It is not the grading key — it is a drift signal, checked
 * by `scripts/check-ground-truth.ts`, and the fallback when a caller has not solved live.
 *
 * The difficulty gradient is deliberate. A one-call lookup and a four-hop aggregation stress
 * completely different things — the cheap task says whether an arm works at all, the expensive one
 * says what the arm costs when the work is real.
 */

import type { Api } from "./api.ts";

export type Answer = string | number;
export type Solver = (api: Api) => Promise<Answer>;

export interface Task {
  readonly id: string;
  readonly difficulty: number;
  readonly question: string;
  /** Operations the task depends on — what `sample(keep: …)` must preserve. */
  readonly requires: readonly string[];
  /** The value last observed. A drift reference, not the grading key. */
  readonly reference: Answer;
  readonly tolerance: number;
  readonly solve: Solver;
  readonly whyThisHard: string;
}

/** Strip accents and case so "josé abílio" grades the same as "JOSE ABILIO". */
function fold(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** Every number in a piece of text, tolerating both 46,960.46 and 46.960,46. */
export function numbersIn(text: string): number[] {
  const out: number[] = [];
  for (const match of text.matchAll(/-?\d[\d.,]*/g)) {
    let cleaned = match[0].replace(/[.,]+$/, "");
    const hasComma = cleaned.includes(",");
    const hasDot = cleaned.includes(".");
    if (hasComma && hasDot) {
      // whichever separator comes last is the decimal one
      const decimal = cleaned.lastIndexOf(",") > cleaned.lastIndexOf(".") ? "," : ".";
      const thousands = decimal === "," ? "." : ",";
      cleaned = cleaned.split(thousands).join("").replace(decimal, ".");
    } else if (hasComma) {
      const tail = cleaned.split(",").at(-1) ?? "";
      cleaned = tail.length === 3 ? cleaned.split(",").join("") : cleaned.replace(",", ".");
    }
    const value = Number(cleaned);
    if (Number.isFinite(value)) out.push(value);
  }
  return out;
}

/**
 * Grade a free-text response against what the API said, falling back to the last known value.
 *
 * Deliberately not an LLM judge. Models are asked for the value alone, so this looks for the value:
 * a numeric answer must appear as a number, a textual one as a substring. The failure mode is a
 * false positive when a model pads its reply with unrelated figures, which is why the prompt asks
 * for the final value only.
 */
export function check(task: Task, response: string, expected?: Answer): boolean {
  const target = expected ?? task.reference;
  if (typeof target === "number") {
    return numbersIn(response).some((n) => Math.abs(n - target) <= task.tolerance);
  }
  return fold(response).includes(fold(target));
}

type Rows = { dados: Record<string, unknown>[] };

const dados = (body: unknown): Record<string, unknown>[] => (body as Rows).dados ?? [];

export const TASKS: readonly Task[] = [
  {
    id: "t1-civil-name",
    difficulty: 1,
    question: "What is the civil name (nomeCivil) of the deputy whose id is 204554?",
    requires: ["get_deputados"],
    reference: "JOSE ABILIO SILVA DE SANTANA",
    tolerance: 0,
    whyThisHard:
      "It is not. One call, one field, no filtering. This is the floor: an arm that cannot do this " +
      "is broken, and the cost recorded here is close to the cost of the exposure itself.",
    solve: async (api) => {
      const body = (await api.get("/deputados/204554")).body as { dados: { nomeCivil: string } };
      return body.dados.nomeCivil;
    },
  },
  {
    id: "t2-acre-headcount",
    difficulty: 2,
    question: "How many deputies currently represent the state of Acre (UF 'AC')?",
    requires: ["list_deputados"],
    reference: 8,
    tolerance: 0,
    whyThisHard:
      "One call, but the agent has to find the filter parameter and then count rather than read. " +
      "Acre is the smallest delegation, so the payload stays modest on purpose.",
    solve: async (api) => dados((await api.get("/deputados", { siglaUf: "AC", itens: 100 })).body).length,
  },
  {
    id: "t3-march-expenses",
    difficulty: 3,
    question:
      "What was the total value (valorLiquido) of all expenses filed by deputy Socorro Neri in March 2024?",
    requires: ["list_deputados", "list_deputados_despesas"],
    reference: 46960.46,
    tolerance: 0.01,
    whyThisHard:
      "Two hops — name to id, then expenses — plus a sum. The trap is pagination: there are 24 " +
      "records and the default page size is 15, so an agent that does not read the parameters " +
      "returns a confidently wrong number.",
    solve: async (api) => {
      const found = dados((await api.get("/deputados", { nome: "Socorro Neri", siglaUf: "AC" })).body);
      const id = found[0]?.id;
      // 24 records against a default page size of 15: the total is only right if the agent noticed.
      const rows = dados(
        (await api.get(`/deputados/${id}/despesas`, { ano: 2024, mes: 3, itens: 100 })).body,
      );
      const total = rows.reduce((sum, row) => sum + Number(row.valorLiquido ?? 0), 0);
      return Math.round(total * 100) / 100;
    },
  },
  {
    id: "t4-sao-paulo-yes-votes",
    difficulty: 4,
    question:
      "In the vote (votação) with id '2400758-37', how many deputies from São Paulo (SP) voted 'Sim'?",
    requires: ["list_votacoes_votos"],
    reference: 22,
    tolerance: 0,
    whyThisHard:
      "One call, and that is the point: the response is 366 nested records and roughly 150 kB. This " +
      "is where returning a payload whole stops being free. The endpoint also rejects `itens` with " +
      "a 400, so an agent that assumes it can page has to recover.",
    solve: async (api) => {
      const votes = dados((await api.get("/votacoes/2400758-37/votos")).body);
      return votes.filter(
        (v) => v.tipoVoto === "Sim" && (v.deputado_ as { siglaUf?: string })?.siglaUf === "SP",
      ).length;
    },
  },
  {
    id: "t5-session-party-no-votes",
    difficulty: 5,
    question:
      "The vote (votação) with id '2400758-37' was held during a session (evento). Considering every " +
      "vote held in that same session, which political party cast the most 'Não' votes in total?",
    requires: ["get_votacoes", "list_eventos_votacoes", "list_votacoes_votos"],
    reference: "PT",
    tolerance: 0,
    whyThisHard:
      "Four hops with a fan-out and no shortcut: the session id is only on the vote's detail record, " +
      "its sibling votes have to be listed, and each one's ballot fetched. Two of the three return " +
      "no nominal votes, so the agent has to tell an empty result from a failure.",
    solve: async (api) => {
      const detail = (await api.get("/votacoes/2400758-37")).body as { dados: { idEvento: number } };
      const siblings = dados((await api.get(`/eventos/${detail.dados.idEvento}/votacoes`)).body);
      const tally = new Map<string, number>();
      for (const sibling of siblings) {
        for (const vote of dados((await api.get(`/votacoes/${sibling.id}/votos`)).body)) {
          if (vote.tipoVoto !== "Não") continue;
          const party = (vote.deputado_ as { siglaPartido?: string })?.siglaPartido ?? "?";
          tally.set(party, (tally.get(party) ?? 0) + 1);
        }
      }
      return [...tally.entries()].sort(([, a], [, b]) => b - a)[0]?.[0] ?? "";
    },
  },
];

export function byId(id: string): Task {
  const found = TASKS.find((task) => task.id === id);
  if (!found) throw new Error(`unknown task: '${id}'`);
  return found;
}

/** Every operation the suite depends on — what `sample(keep: …)` must preserve. */
export function requiredOperations(): string[] {
  return [...new Set(TASKS.flatMap((task) => task.requires))];
}
