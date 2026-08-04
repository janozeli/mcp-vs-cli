/**
 * The trial boundary: the harness owns secrets and talks to the model's provider; the experiment
 * must own neither.
 *
 * Confinement is ai-jail over bubblewrap, applied per `bash` invocation through pi's `shellPath`
 * setting. The wrapper is written once by the harness and is byte-identical for every arm, so the
 * jail belongs to the shared harness, never to an arm. Inside it the trial's working directory is
 * the only persistent, visible piece of the filesystem: the repository, `$HOME` and the operator's
 * dotfiles do not exist, and `$HOME` and `/tmp` are a fresh tmpfs on every call.
 *
 * The other two pieces are assertions rather than mechanisms, in the same spirit as measuring API
 * divergence instead of freezing the API (invariant 3): a credential-shaped environment variable
 * aborts the run loudly before a session exists, and network use is audited from the trace after
 * the fact rather than blocked — the live API has to stay reachable, and a model probing beyond it
 * is a finding to report, not an accident to hide.
 */

/**
 * Environment variable names that look like credentials and carry a value.
 *
 * Every child of the harness — the model's `bash`, the MCP server the adapter spawns — inherits
 * the harness environment, so anything matched here would cross the boundary. The harness aborts
 * on a match instead of filtering: a leak has to be an error someone sees, never a variable a
 * trial quietly carried.
 */
export function leakyEnvNames(env: Readonly<Record<string, string | undefined>>): string[] {
  const suffixes = ["KEY", "TOKEN", "SECRET", "PASSWORD"];
  return Object.keys(env)
    .filter((name) => {
      const upper = name.toUpperCase();
      return suffixes.some((suffix) => upper === suffix || upper.endsWith(`_${suffix}`));
    })
    .filter((name) => Boolean(env[name]?.trim()))
    .sort();
}

/**
 * The shell wrapper pi's `shellPath` points at.
 *
 * `--exec` keeps the jail silent, so tool output is byte-identical to an unjailed shell — a banner
 * would both contaminate every tool result and tell the model it is being confined.
 * `--no-save-config` keeps ai-jail from writing its policy file into the trial's working
 * directory, which the model can list.
 */
export function jailWrapper(aiJailPath: string): string {
  return `#!/bin/sh\nexec "${aiJailPath}" --no-save-config --exec bash "$@"\n`;
}

/**
 * Hosts named in URLs inside tool-call arguments, deduplicated and sorted.
 *
 * This is the audit half of the network boundary: egress stays open because the live API must be
 * reachable, and what the model chose to contact is read from the trace afterwards. Only the
 * *arguments* are scanned — the API's own payloads reference sibling hosts (photo URLs and the
 * like) that the model never chose. A URL the model builds without a scheme is not caught; the
 * audit is a tripwire, not a proof.
 */
export function referencedHosts(entries: readonly unknown[]): string[] {
  const hosts = new Set<string>();
  for (const entry of entries) {
    const content = (entry as { message?: { content?: unknown } }).message?.content;
    if (!Array.isArray(content)) continue;
    for (const part of content) {
      const piece = part as { type?: string; arguments?: unknown };
      if (piece.type !== "toolCall") continue;
      const text = JSON.stringify(piece.arguments ?? {});
      for (const match of text.matchAll(/https?:\/\/([^/\s"'\\<>)]+)/gi)) {
        const host = match[1]?.split("@").pop()?.split(":")[0]?.toLowerCase();
        if (host) hosts.add(host);
      }
    }
  }
  return [...hosts].sort();
}
