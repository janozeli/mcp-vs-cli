/**
 * One place that decides how every run is executed, so the arms differ only where they should.
 *
 * Every arm gets the same harness, the same objective, the same settings and unrestricted `bash`.
 * What differs is only what has been *installed* on top: an MCP server, a binary on `PATH`, or
 * nothing. The harness is deepseek-harness (dsh), vendored at a pinned commit and composed from its
 * published core packages the way its own agent-loop tests compose them — dsh documents no
 * TypeScript embedding surface, and the npm launcher resolves plugin versions at boot without a
 * lockfile, which a recomputable experiment cannot accept while the project is a developer preview.
 *
 * The composition is minimal by design, not tuned: the exact plugin set an arm needs to have `bash`
 * and its installation, and nothing else. Three exclusions are the measurement itself:
 *
 * **No compaction, no pruning, no spill.** dsh's base profile compacts context, prunes oversized
 * tool results and spills large payloads to files. Each one silently rewrites what "context" means,
 * so none of those plugins is mounted here.
 *
 * **No retries.** The OpenRouter route is declared with `maxRetries: 0`; retry tokens are not the
 * arm's cost.
 *
 * **Nothing is read from the machine.** The credential store is a file this run writes into a
 * temporary directory, sessions are in memory, and no settings document is mounted, so no
 * operator-level configuration, skill or MCP server can join a trial.
 *
 * **Confinement is dsh's own sandbox, identical for every arm.** Every `bash` call is wrapped by
 * `dsh-bash-sandbox` over `dsh-sandbox-local` (bubblewrap, then Landlock), scoped to the trial's
 * working directory. The stack fails closed: on a machine that cannot confine, `bash` calls error
 * rather than run unconfined, so jailed and unjailed numbers cannot mix. The harness still aborts
 * if a credential-shaped environment variable would be inherited, and the hosts the model
 * referenced are read back from the trace.
 */

import { randomUUID } from "node:crypto";
import { chmod, copyFile, mkdir, mkdtemp, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import * as Agent from "#dsh/agent";
import * as AgentLoop from "#dsh/agent-loop";
import * as BashSandbox from "#dsh/bash-sandbox";
import { Context } from "#dsh/cordis";
import * as CredentialsLocal from "#dsh/credentials-local";
import * as Llm from "#dsh/llm";
import * as LlmPiAi from "#dsh/llm-pi-ai";
import * as McpClient from "#dsh/mcp-client";
import * as SandboxLocal from "#dsh/sandbox-local";
import * as SandboxPolicy from "#dsh/sandbox-policy";
import * as Session from "#dsh/session";
import * as ShellEnv from "#dsh/shell-env";
import * as SubprocessLocal from "#dsh/subprocess-local";
import * as SystemPrompt from "#dsh/system-prompt";
import * as TokenMeter from "#dsh/token-meter";
import * as ToolBash from "#dsh/tool-bash";
import * as Tools from "#dsh/tools";
import { leakyEnvNames, referencedHosts } from "./jail.ts";

/** The objective, byte-identical in every arm. It states the goal and never the procedure. */
export const OBJECTIVE =
  "Answer the user's question using the tools available to you. Reply with the final value only.";

export const PROVIDER = "openrouter";
export const MODEL = "deepseek/deepseek-v4-flash";

/** What an arm installs on top of the shared harness. */
export interface Arm {
  readonly key: string;
  /** MCP servers to install, by name and command. The client spawns them on the host. */
  readonly mcpServers: Readonly<Record<string, string>>;
  /**
   * Files copied into the trial's working directory before the run — the installation itself.
   * Copied rather than referenced because inside the sandbox the repository does not exist; a
   * `PATH` entry pointing at it would be an address the model can read but never reach.
   */
  readonly installs: readonly { readonly from: string; readonly to: string }[];
  /** Directories prepended to `PATH`, relative to the trial's working directory. */
  readonly pathAdditions: readonly string[];
  readonly why: string;
}

/**
 * One model call's accounting, from the provider's own usage as dsh records it on the session log.
 * dsh's pi-ai adapter does not surface the provider's reasoning-token split or cost, so neither is
 * reported here — a column that is silently zero would be worse than an honest absence.
 */
export interface Turn {
  readonly input: number;
  readonly output: number;
  readonly cacheRead: number;
  readonly cacheWrite: number;
  /** What the model actually carried: dsh reports `input` net of cache reads. */
  readonly context: number;
}

export interface RunResult {
  readonly arm: string;
  readonly answer: string;
  readonly turns: readonly Turn[];
  readonly toolCalls: readonly string[];
  /** Every session event, verbatim — the trace invariant 4 rests on. */
  readonly entries: readonly unknown[];
  /** What the model could actually call. An arm that installed a tool it never received is a bug. */
  readonly activeTools: readonly string[];
  /** Installation and turn failures. A dead installation must be loud, never a quiet number. */
  readonly errors: readonly string[];
  /** dsh's own context measurement of the final session, not a derivation of ours. */
  readonly contextTokens: number | null;
  /** Whether that measurement anchors on provider usage or fell back to dsh's local heuristic. */
  readonly contextSource: string | null;
  readonly peakContext: number;
  readonly totalOutput: number;
  readonly aborted?: string;
  /**
   * Confinement marker kept for the trace's meta row. dsh's sandbox fails closed — a machine that
   * cannot confine produces failed `bash` calls, never unconfined ones — so this is a recorded
   * property of the composition rather than a per-run probe.
   */
  readonly jailed: boolean;
  /** Hosts named in tool-call arguments — the audit half of the open-network boundary. */
  readonly hosts: readonly string[];
}

export interface RunOptions {
  readonly arm: Arm;
  readonly question: string;
  readonly apiKey: string;
  readonly cwd: string;
  readonly model?: string;
  readonly provider?: string;
  /** Wall-clock ceiling for one trial. A run that stalls has to become a result, not a hang. */
  readonly timeoutMs?: number;
}

/** How long a single trial may run before it is abandoned and recorded as such. */
export const TRIAL_TIMEOUT_MS = 180_000;

/** Cordis plugins export their callable as `default` when built; tests pass the namespace. */
// biome-ignore lint/suspicious/noExplicitAny: the plugin union cordis accepts is not exported
const plugin = (m: unknown): any => (m as { default?: unknown }).default ?? m;

const textOf = (content: unknown): string =>
  Array.isArray(content)
    ? content
        .filter((block: { type?: string }) => block.type === "text")
        .map((block: { text?: string }) => block.text ?? "")
        .join("")
    : "";

/**
 * Run one question through one arm.
 *
 * Composes dsh in-process from its core packages — the same shape as its own agent-loop test
 * suite — because the session log, the tool registry and per-turn provider usage are only
 * reachable from inside the tree; the shipped one-shot runner prints final text and discards
 * everything a benchmark needs.
 */
export async function run(options: RunOptions): Promise<RunResult> {
  const { arm, question, apiKey, cwd } = options;
  const provider = options.provider ?? PROVIDER;
  const modelId = options.model ?? MODEL;

  // Every child of this process — the model's bash, the MCP server the client spawns — inherits
  // this environment. A credential here would cross into the trial, so it is an error someone
  // sees, never a variable a trial quietly carried. The caller keeps its key in a local; the trial
  // reads it back through dsh's file-backed credential store, never the environment.
  const leaks = leakyEnvNames(process.env);
  if (leaks.length > 0) {
    throw new Error(
      `refusing to run: the trial would inherit credential-shaped environment variables: ${leaks.join(", ")}`,
    );
  }

  // A harness home this run owns. Nothing on the machine is read: no operator settings document,
  // profile, skill or MCP server can join, and the repository's own AGENTS.md or CLAUDE.md cannot
  // be injected into a cell.
  const agentDir = await mkdtemp(join(tmpdir(), "mcp-vs-cli-"));
  const credentialsPath = join(agentDir, ".credentials.yaml");
  await writeFile(credentialsPath, `OPENROUTER_API_KEY: ${apiKey}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });

  // The installation is copied into the trial's working directory: it has to exist inside the
  // sandbox, and the copy carries no path back to the repository.
  for (const install of arm.installs) {
    const destination = join(cwd, install.to);
    await mkdir(dirname(destination), { recursive: true });
    await copyFile(install.from, destination);
    await chmod(destination, (await stat(install.from)).mode);
  }

  const previousPath = process.env.PATH ?? "";
  if (arm.pathAdditions.length > 0) {
    const additions = arm.pathAdditions.map((path) => join(cwd, path));
    process.env.PATH = [...additions, previousPath].join(delimiter);
  }

  const errors: string[] = [];
  const ctx = new Context();

  try {
    await ctx.plugin(plugin(Llm));
    await ctx.plugin(plugin(CredentialsLocal), { path: credentialsPath });
    // A catalog route: endpoint, protocol and model list come from pi-ai's own registry, exactly
    // as they did when pi was the harness — only the credential reference is ours.
    await ctx.plugin(plugin(LlmPiAi), {
      providers: {
        [provider]: {
          apiKeyEnv: "OPENROUTER_API_KEY",
          retryPolicy: { mode: "normal", maxRetries: 0 },
        },
      },
    });
    await ctx.plugin(plugin(Session));
    await ctx.plugin(plugin(SystemPrompt), {
      persona: OBJECTIVE,
      includeHarnessIdentity: false,
      includeRuntimeContext: false,
    });
    await ctx.plugin(plugin(Tools));
    await ctx.plugin(plugin(ShellEnv), { dshHome: agentDir });
    await ctx.plugin(plugin(SubprocessLocal));
    await ctx.plugin(plugin(SandboxLocal));
    await ctx.plugin(plugin(SandboxPolicy), { mode: "workspace-write", workspaceRoot: cwd });
    await ctx.plugin(plugin(BashSandbox));
    await ctx.plugin(plugin(ToolBash));
    await ctx.plugin(plugin(Agent));
    await ctx.plugin(plugin(AgentLoop), { agents: [] });
    await ctx.plugin(plugin(TokenMeter));

    // An arm that installs MCP servers gets one client instance per server, configured the way a
    // dsh user's profile patch would name them. The client spawns the server on the host and
    // registers its tools as `mcp__<server>__<operation>`.
    for (const [serverName, command] of Object.entries(arm.mcpServers)) {
      const [bin, ...args] = command.split(" ");
      if (!bin) {
        errors.push(`mcp ${serverName}: empty command`);
        continue;
      }
      try {
        await ctx.plugin(McpClient, {
          transport: "stdio",
          serverName,
          command: bin,
          args,
          cwd,
          env: {},
          toolCallTimeoutMs: 30_000,
          // A server that cannot start must fail the mount loudly — the arm's installation is
          // dead, and the trial has to say so rather than run as a quiet baseline.
          failOnStartupError: true,
        });
      } catch (error) {
        errors.push(`mcp ${serverName}: ${error instanceof Error ? error.message : error}`);
      }
    }

    // The model-facing registry, read back rather than assumed: a dead installation has to be
    // loud. Every arm must offer bash; an MCP arm must offer its server's tools.
    const activeTools = ctx.tools.schemas().map((schema: { name: string }) => schema.name);
    for (const serverName of Object.keys(arm.mcpServers)) {
      if (!activeTools.some((name: string) => name.startsWith(`mcp__${serverName}__`))) {
        errors.push(`mcp ${serverName}: installed but no mcp__${serverName}__* tool registered`);
      }
    }

    const { agent, dispose } = await ctx.agents.create({
      sessionId: Session.SessionId(`session-${randomUUID()}`),
      meta: { cwd },
      agentOptions: { provider, model: modelId },
    });

    try {
      await agent.whenIdle();

      // A trial that never returns is a result too. Abandoning it keeps the tokens it did spend
      // and says so, rather than stopping the batch on a wall clock and leaving nothing behind.
      const ceiling = options.timeoutMs ?? TRIAL_TIMEOUT_MS;
      let timedOut = false;
      const alarm = setTimeout(() => {
        timedOut = true;
        agent.cancel({ kind: "user" });
      }, ceiling);
      try {
        agent.followup(
          Llm.createUserMessage({
            content: [{ type: "text", text: question }],
            source: { kind: "user" },
          }),
        );
        await agent.whenIdle();
      } finally {
        clearTimeout(alarm);
      }

      const turns: Turn[] = [];
      const toolCalls: string[] = [];
      let answer = "";
      for (const event of agent.session.events as readonly {
        type: string;
        data: Record<string, unknown>;
      }[]) {
        if (event.type === "tool/call") toolCalls.push(String(event.data.name));
        if (event.type === "turn/end") {
          const reason = event.data.reason as
            | { kind: string; error?: { code?: string; message?: string } }
            | undefined;
          if (reason?.kind === "error") {
            errors.push(`turn: ${reason.error?.code ?? "?"}: ${reason.error?.message ?? "?"}`);
          }
        }
        if (event.type !== "assistant/message") continue;
        const usage = event.data.usage as
          | {
              inputTokens: number;
              outputTokens: number;
              cacheReadTokens?: number;
              cacheWriteTokens?: number;
            }
          | undefined;
        if (usage) {
          const input = usage.inputTokens;
          const cacheRead = usage.cacheReadTokens ?? 0;
          turns.push({
            input,
            output: usage.outputTokens,
            cacheRead,
            cacheWrite: usage.cacheWriteTokens ?? 0,
            context: input + cacheRead,
          });
        }
        const text = textOf((event.data.message as { content?: unknown })?.content);
        if (text) answer = text;
      }

      // dsh's own measurement of the final session, anchored on provider usage when the last
      // request's envelope still matches, and honestly labelled when it had to estimate.
      const measurement = ctx.tokenMeter.measure(agent.session) as {
        totalTokens?: number;
        baseline?: { kind?: string };
      };

      const entries = [...agent.session.events];
      return {
        arm: arm.key,
        answer: answer.trim(),
        turns,
        toolCalls,
        entries,
        activeTools,
        errors,
        jailed: true,
        hosts: referencedHosts(entries),
        ...(timedOut ? { aborted: `no answer within ${ceiling} ms` } : {}),
        contextTokens: measurement.totalTokens ?? null,
        contextSource: measurement.baseline?.kind ?? null,
        peakContext: Math.max(0, ...turns.map((turn) => turn.context)),
        totalOutput: turns.reduce((sum, turn) => sum + turn.output, 0),
      };
    } finally {
      await dispose();
    }
  } finally {
    process.env.PATH = previousPath;
    // Disposing the root fiber unwinds every plugin, which is what disconnects the MCP client and
    // stops the server it spawned. Runs are sequential and repeated, so a trial that does not
    // release what it started would accumulate one stray server per repeat.
    await ctx.fiber.dispose();
  }
}
