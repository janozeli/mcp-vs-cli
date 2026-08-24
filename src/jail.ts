/**
 * The trial boundary: the harness owns secrets and talks to the model's provider; the experiment
 * must own neither.
 *
 * Confinement itself is dsh's sandbox stack (`dsh-bash-sandbox` over `dsh-sandbox-local`:
 * bubblewrap, then Landlock), mounted once in the harness and identical for every arm, scoped to
 * the trial's working directory and failing closed where the machine cannot confine. What remains
 * here are the two assertions around it, in the same spirit as measuring API divergence instead of
 * freezing the API (invariant 3): a credential-shaped environment variable aborts the run loudly
 * before a session exists, and network use is audited from the trace after the fact rather than
 * blocked — the live API has to stay reachable, and a model probing beyond it is a finding to
 * report, not an accident to hide.
 */

/**
 * Environment variable names that look like credentials and carry a value.
 *
 * Every child of the harness — the model's `bash`, the MCP server the client spawns — inherits
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
 * Hosts named in URLs inside tool-call arguments, deduplicated and sorted.
 *
 * This is the audit half of the network boundary: egress stays open because the live API must be
 * reachable, and what the model chose to contact is read from the trace afterwards. Only the
 * *arguments* are scanned — the API's own payloads reference sibling hosts (photo URLs and the
 * like) that the model never chose. A URL the model builds without a scheme is not caught; the
 * audit is a tripwire, not a proof.
 *
 * Entries are dsh session events: a `tool/call` event carries the model's arguments as the JSON
 * string it produced.
 */
export function referencedHosts(entries: readonly unknown[]): string[] {
  const hosts = new Set<string>();
  for (const entry of entries) {
    const event = entry as { type?: string; data?: { arguments?: unknown } };
    if (event.type !== "tool/call") continue;
    const text =
      typeof event.data?.arguments === "string"
        ? event.data.arguments
        : JSON.stringify(event.data?.arguments ?? {});
    for (const match of text.matchAll(/https?:\/\/([^/\s"'\\<>)]+)/gi)) {
      const host = match[1]?.split("@").pop()?.split(":")[0]?.toLowerCase();
      if (host) hosts.add(host);
    }
  }
  return [...hosts].sort();
}
