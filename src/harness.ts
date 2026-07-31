/**
 * One place that decides how every run is executed, so the arms differ only where they should.
 *
 * Every arm gets the same harness, the same objective, the same settings and unrestricted `bash`.
 * What differs is only what has been *installed* on top: an MCP server, a binary on `PATH`, or
 * nothing. That is the point of running inside a stock harness — an arm should be an installation,
 * not a code path we wrote.
 *
 * Three settings here are not conveniences, they are the measurement:
 *
 * **Compaction is disabled.** pi compacts context automatically. Left on, a benchmark about context
 * cost measures pi's compactor — and pi's own `getContextUsage()` reports null tokens until a
 * post-compaction assistant response exists, so the metric would go quiet exactly when it mattered.
 *
 * **Retries are disabled.** Retry tokens are not the arm's cost.
 *
 * **Nothing is read from the machine.** Settings and session are in memory and the system prompt is
 * overridden, so no globally installed extension, skill or MCP server can join the run. An earlier
 * attempt that inherited the operator's own configuration carried about 29,000 extra tokens of
 * context per turn.
 */

import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  createAgentSession,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

/**
 * pi keeps MCP out of its core by design, so the MCP arm installs it the way a user would: an
 * extension package plus a standard `.mcp.json`. How the adapter then surfaces a server to the model
 * is the adapter's decision, not ours — which is the whole point of measuring inside a stock harness.
 */
const MCP_ADAPTER = new URL("../node_modules/pi-mcp-adapter", import.meta.url).pathname.replace(
  /^\/([A-Za-z]:)/,
  "$1",
);

/** The objective, byte-identical in every arm. It states the goal and never the procedure. */
export const OBJECTIVE =
  "Answer the user's question using the tools available to you. Reply with the final value only.";

export const PROVIDER = "openrouter";
export const MODEL = "deepseek/deepseek-v4-flash";

/** What an arm installs on top of the shared harness. */
export interface Arm {
  readonly key: string;
  /** Built-in pi tools the arm may use. Every arm gets `bash`; that is the common denominator. */
  readonly tools: readonly string[];
  /** MCP servers to install, by name and command. */
  readonly mcpServers: Readonly<Record<string, string>>;
  /** Directories prepended to `PATH`, so an installed binary is reachable. */
  readonly pathAdditions: readonly string[];
  readonly why: string;
}

export interface Turn {
  readonly input: number;
  readonly output: number;
  readonly reasoning: number;
  readonly cacheRead: number;
  readonly cacheWrite: number;
  readonly cost: number;
  /** What the model actually carried: pi reports `input` net of cache reads. */
  readonly context: number;
}

export interface RunResult {
  readonly arm: string;
  readonly answer: string;
  readonly turns: readonly Turn[];
  readonly toolCalls: readonly string[];
  readonly contextTokens: number | null;
  readonly contextWindow: number | null;
  readonly peakContext: number;
  readonly totalOutput: number;
  readonly totalReasoning: number;
  readonly cost: number;
  readonly aborted?: string;
}

/** Settings that make a run measurable rather than merely runnable. */
function settings() {
  return SettingsManager.inMemory({
    compaction: { enabled: false },
    retry: { enabled: false },
    quietStartup: true,
    enableAnalytics: false,
    enableInstallTelemetry: false,
  });
}

export interface RunOptions {
  readonly arm: Arm;
  readonly question: string;
  readonly apiKey: string;
  readonly cwd: string;
  readonly model?: string;
  readonly provider?: string;
  readonly maxTurns?: number;
}

/**
 * Run one question through one arm.
 *
 * Uses pi's own `AgentSession` rather than a subprocess: the documentation recommends it for
 * TypeScript callers, and it is the only way to supply settings that never touch the filesystem.
 */
export async function run(options: RunOptions): Promise<RunResult> {
  const { arm, question, apiKey, cwd } = options;
  const provider = options.provider ?? PROVIDER;
  const modelId = options.model ?? MODEL;

  // An agent directory this run owns. Nothing on the machine is read: no globally installed
  // extension, skill, prompt template or MCP server can join, and the repository's own AGENTS.md or
  // CLAUDE.md cannot be injected into a cell.
  const agentDir = await mkdtemp(join(tmpdir(), "mcp-vs-cli-"));

  const modelRuntime = await ModelRuntime.create({
    authPath: join(agentDir, "auth.json"),
    modelsStorePath: join(agentDir, "models.json"),
    allowModelNetwork: false,
  });
  modelRuntime.setRuntimeApiKey(provider, apiKey);
  const model = modelRuntime.getModel(provider, modelId);
  if (!model) throw new Error(`unknown model: ${provider}/${modelId}`);

  // An arm that installs MCP servers gets the adapter and a config naming them; every other arm
  // gets neither. Discovery stays off, so nothing else on the machine can join either way.
  const installsMcp = Object.keys(arm.mcpServers).length > 0;
  if (installsMcp) {
    const mcpServers = Object.fromEntries(
      Object.entries(arm.mcpServers).map(([name, command]) => {
        const [bin, ...args] = command.split(" ");
        return [name, { command: bin, args }];
      }),
    );
    await writeFile(join(cwd, ".mcp.json"), `${JSON.stringify({ mcpServers }, null, 2)}
`, "utf8");
  }

  const settingsManager = settings();
  const loader = new DefaultResourceLoader({
    cwd,
    agentDir,
    settingsManager,
    systemPromptOverride: () => OBJECTIVE,
    additionalExtensionPaths: installsMcp ? [MCP_ADAPTER] : [],
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
  });
  await loader.reload();

  const previousPath = process.env.PATH ?? "";
  if (arm.pathAdditions.length > 0) {
    process.env.PATH = [...arm.pathAdditions, previousPath].join(";");
  }

  const turns: Turn[] = [];
  const toolCalls: string[] = [];
  let answer = "";

  try {
    const { session } = await createAgentSession({
      cwd,
      agentDir,
      model,
      modelRuntime,
      tools: [...arm.tools],
      resourceLoader: loader,
      sessionManager: SessionManager.inMemory(),
      settingsManager,
    });

    session.subscribe((event: { type: string; [key: string]: unknown }) => {
      if (event.type === "tool_execution_start") toolCalls.push(String(event.toolName));
      if (event.type !== "message_end") return;
      const message = event.message as { usage?: Record<string, number>; content?: unknown[] };
      const usage = message.usage;
      if (usage?.totalTokens) {
        const input = usage.input ?? 0;
        const cacheRead = usage.cacheRead ?? 0;
        turns.push({
          input,
          output: usage.output ?? 0,
          reasoning: usage.reasoning ?? 0,
          cacheRead,
          cacheWrite: usage.cacheWrite ?? 0,
          cost: (usage.cost as unknown as { total?: number })?.total ?? 0,
          context: input + cacheRead,
        });
      }
      for (const part of message.content ?? []) {
        const piece = part as { type?: string; text?: string };
        if (piece.type === "text" && piece.text) answer = piece.text;
      }
    });

    await session.prompt(question);

    // pi's own estimate, rather than our derivation from per-turn usage.
    const usage = (
      session as { getContextUsage?(): { tokens: number | null; contextWindow: number } }
    ).getContextUsage?.();

    return {
      arm: arm.key,
      answer: answer.trim(),
      turns,
      toolCalls,
      contextTokens: usage?.tokens ?? null,
      contextWindow: usage?.contextWindow ?? null,
      peakContext: Math.max(0, ...turns.map((t) => t.context)),
      totalOutput: turns.reduce((sum, t) => sum + t.output, 0),
      totalReasoning: turns.reduce((sum, t) => sum + t.reasoning, 0),
      cost: turns.reduce((sum, t) => sum + t.cost, 0),
    };
  } finally {
    process.env.PATH = previousPath;
  }
}
