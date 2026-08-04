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
 *
 * **The trial is jailed, identically for every arm.** Every `bash` call runs through the same
 * ai-jail wrapper (see `src/jail.ts`), so the repository, `$HOME` and the operator's machine do not
 * exist inside a trial; a run records whether it was jailed, because jailed and unjailed numbers
 * must never mix silently. The harness aborts if a credential-shaped environment variable would be
 * inherited, and the hosts the model referenced are read back from the trace.
 */

import { chmod, copyFile, mkdir, mkdtemp, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import {
  type AgentSessionRuntime,
  createAgentSessionFromServices,
  createAgentSessionRuntime,
  createAgentSessionServices,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { jailWrapper, leakyEnvNames, referencedHosts } from "./jail.ts";

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
  /** MCP servers to install, by name and command. The client spawns them on the host. */
  readonly mcpServers: Readonly<Record<string, string>>;
  /**
   * Files copied into the trial's working directory before the run — the installation itself.
   * Copied rather than referenced because inside the jail the repository does not exist; a `PATH`
   * entry pointing at it would be an address the model can read but never reach.
   */
  readonly installs: readonly { readonly from: string; readonly to: string }[];
  /** Directories prepended to `PATH`, relative to the trial's working directory. */
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
  /** Every session entry, verbatim — the trace invariant 4 rests on. */
  readonly entries: readonly unknown[];
  /** What the model could actually call. An arm that installed a tool it never received is a bug. */
  readonly activeTools: readonly string[];
  /** Anything an extension reported. A dead installation must be loud, never a quiet number. */
  readonly extensionErrors: readonly string[];
  readonly contextTokens: number | null;
  readonly contextWindow: number | null;
  readonly peakContext: number;
  readonly totalOutput: number;
  readonly totalReasoning: number;
  readonly cost: number;
  readonly aborted?: string;
  /** Whether every `bash` call ran inside the jail. Jailed and unjailed numbers must never mix. */
  readonly jailed: boolean;
  /** Hosts named in tool-call arguments — the audit half of the open-network boundary. */
  readonly hosts: readonly string[];
}

/** Settings that make a run measurable rather than merely runnable. */
function settings(shellPath?: string) {
  return SettingsManager.inMemory({
    ...(shellPath ? { shellPath } : {}),
    compaction: { enabled: false },
    retry: { enabled: false },
    quietStartup: true,
    enableAnalytics: false,
    enableInstallTelemetry: false,
  });
}

/** A session action that has no meaning inside a single-prompt trial. */
function notDuringATrial(name: string): never | (() => never) {
  return () => {
    throw new Error(`${name} is not available during a trial: a trial is one prompt in one session`);
  };
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

  // Every child of this process — the model's bash, the MCP server the adapter spawns — inherits
  // this environment. A credential here would cross into the trial, so it is an error someone
  // sees, never a variable a trial quietly carried. The caller keeps its key in a local.
  const leaks = leakyEnvNames(process.env);
  if (leaks.length > 0) {
    throw new Error(
      `refusing to run: the trial would inherit credential-shaped environment variables: ${leaks.join(", ")}`,
    );
  }

  // An agent directory this run owns. Nothing on the machine is read: no globally installed
  // extension, skill, prompt template or MCP server can join, and the repository's own AGENTS.md or
  // CLAUDE.md cannot be injected into a cell.
  const agentDir = await mkdtemp(join(tmpdir(), "mcp-vs-cli-"));

  // The jail, when the machine can provide one. The wrapper lives in the agent directory — the
  // harness's territory, not the trial's — and is identical for every arm: confinement is part of
  // the shared harness, never of an arm. Without ai-jail the run still happens, marked unjailed.
  const aiJail = Bun.which("ai-jail");
  const shellPath = aiJail ? join(agentDir, "jail.sh") : undefined;
  if (aiJail && shellPath) {
    await writeFile(shellPath, jailWrapper(aiJail), { mode: 0o755 });
  }
  const jailed = shellPath !== undefined;

  // The installation is copied into the trial's working directory: it has to exist inside the
  // jail, and the copy carries no path back to the repository.
  for (const install of arm.installs) {
    const destination = join(cwd, install.to);
    await mkdir(dirname(destination), { recursive: true });
    await copyFile(install.from, destination);
    await chmod(destination, (await stat(install.from)).mode);
  }

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
    await writeFile(
      join(cwd, ".mcp.json"),
      `${JSON.stringify({ mcpServers }, null, 2)}
`,
      "utf8",
    );
  }

  const settingsManager = settings(shellPath);
  const resourceLoaderOptions = {
    systemPromptOverride: () => OBJECTIVE,
    additionalExtensionPaths: installsMcp ? [MCP_ADAPTER] : [],
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
  };

  const previousPath = process.env.PATH ?? "";
  if (arm.pathAdditions.length > 0) {
    const additions = arm.pathAdditions.map((path) => join(cwd, path));
    process.env.PATH = [...additions, previousPath].join(delimiter);
  }

  const turns: Turn[] = [];
  const toolCalls: string[] = [];
  const extensionErrors: string[] = [];
  let answer = "";

  // Held rather than passed inline: it owns the transcript, and reading it back afterwards is the
  // only way to see what each tool call actually returned. Without that, a run that worked and a run
  // that gave up and improvised produce the same numbers.
  const sessionManager = SessionManager.inMemory();

  // The runtime host rather than a bare session: it is what owns teardown. `session.dispose()` stops
  // the agent but never emits `session_shutdown`, so an arm that spawned an MCP server left the child
  // alive and the process hanging — four minutes per trial, with the answer already printed.
  let runtime: AgentSessionRuntime | undefined;

  try {
    runtime = await createAgentSessionRuntime(
      async (target) => {
        const services = await createAgentSessionServices({
          cwd: target.cwd,
          agentDir: target.agentDir,
          settingsManager,
          modelRuntime,
          resourceLoaderOptions,
        });
        const created = await createAgentSessionFromServices({
          services,
          sessionManager: target.sessionManager,
          ...(target.sessionStartEvent ? { sessionStartEvent: target.sessionStartEvent } : {}),
          model,
          tools: [...arm.tools],
        });
        return { ...created, services, diagnostics: services.diagnostics };
      },
      { cwd, agentDir, sessionManager },
    );
    const session = runtime.session;

    // Loading an extension is not the same as activating it. `bindExtensions` is what emits
    // `session_start`, and every real pi mode calls it; the MCP adapter starts its servers on that
    // event. Without this the arm's `mcp` tool answers "MCP not initialized" and the model, finding
    // the installation dead, debugs it and falls back to curl — which is exactly what it did.
    await session.bindExtensions({
      mode: "print",
      // A trial is one prompt in one session. Forking, switching and reloading exist so an
      // interactive user can steer a run; here they would silently change what is being measured, so
      // they refuse rather than pretend.
      commandContextActions: {
        waitForIdle: () => session.waitForIdle(),
        newSession: notDuringATrial("newSession"),
        fork: notDuringATrial("fork"),
        navigateTree: notDuringATrial("navigateTree"),
        switchSession: notDuringATrial("switchSession"),
        reload: notDuringATrial("reload"),
      },
      onError: (err: { extensionPath: string; error: unknown }) => {
        extensionErrors.push(`${err.extensionPath}: ${err.error}`);
      },
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

    // A trial that never returns is a result too. Abandoning it keeps the tokens it did spend and
    // says so, rather than stopping the batch on a wall clock and leaving nothing behind.
    const ceiling = options.timeoutMs ?? TRIAL_TIMEOUT_MS;
    let timedOut = false;
    const alarm = setTimeout(() => {
      timedOut = true;
      void session.abort();
    }, ceiling);
    try {
      await session.prompt(question);
    } finally {
      clearTimeout(alarm);
    }

    // pi's own estimate, rather than our derivation from per-turn usage.
    const usage = (
      session as { getContextUsage?(): { tokens: number | null; contextWindow: number } }
    ).getContextUsage?.();

    const entries = sessionManager.getEntries();
    return {
      arm: arm.key,
      answer: answer.trim(),
      turns,
      toolCalls,
      entries,
      activeTools: session.getActiveToolNames(),
      extensionErrors,
      jailed,
      hosts: referencedHosts(entries),
      ...(timedOut ? { aborted: `no answer within ${ceiling} ms` } : {}),
      contextTokens: usage?.tokens ?? null,
      contextWindow: usage?.contextWindow ?? null,
      peakContext: Math.max(0, ...turns.map((t) => t.context)),
      totalOutput: turns.reduce((sum, t) => sum + t.output, 0),
      totalReasoning: turns.reduce((sum, t) => sum + t.reasoning, 0),
      cost: turns.reduce((sum, t) => sum + t.cost, 0),
    };
  } finally {
    process.env.PATH = previousPath;
    // Emits `session_shutdown`, which is what stops the MCP servers the arm installed. Runs are
    // sequential and repeated, so a trial that does not release what it started would accumulate one
    // stray server per repeat.
    await runtime?.dispose();
  }
}
