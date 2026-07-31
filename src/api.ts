/**
 * The one way this benchmark reaches the API: live, every time, storing nothing.
 *
 * There is no cache and no recorded corpus. A trial sees the API as it is at the moment it runs,
 * which is the same thing an agent in the wild sees. The cost of that choice is deliberate and is
 * stated in the README rather than engineered away: two arms answering the same question can, in
 * principle, receive different data, and a third party cannot re-execute a past run.
 *
 * What replaces the guarantee is measurement. Every response is written to the trial's trace
 * verbatim, so a comparison can be checked *after the fact* for whether its arms actually saw the
 * same bytes. Detecting the problem is honest; pretending a frozen corpus made it impossible was
 * only true inside the freezer.
 */

import ky, { HTTPError, type KyInstance } from "ky";

/** Pinned so the arms cannot differ by content negotiation. */
const HEADERS = { Accept: "application/json" } as const;

export interface ApiResponse {
  readonly status: number;
  readonly body: unknown;
  readonly url: string;
  readonly ok: boolean;
}

/**
 * A stable text form of a request.
 *
 * Not used for storage — nothing is stored. It exists so a trace can be read, and so parity between
 * two arms can be checked on requests that mean the same thing regardless of the order or the types
 * the caller happened to use.
 */
export function canonicalRequest(method: string, path: string, params: Record<string, unknown> = {}): string {
  const query = Object.entries(params)
    .map(([k, v]) => [String(k), String(v)] as const)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([k, v]) => `${k}=${v}`)
    .join("&");
  return `${method.toUpperCase()} ${path}${query ? `?${query}` : ""}`;
}

/** A thin live GET client. Holds a connection, never a response. */
export class Api {
  readonly baseUrl: string;
  calls = 0;
  private readonly client: KyInstance;

  constructor(baseUrl: string, options: { pauseMs?: number } = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    const pauseMs = options.pauseMs ?? 0;
    this.client = ky.create({
      headers: HEADERS,
      timeout: 60_000,
      // The subject is a public, unauthenticated service run at public expense. Retries are bounded
      // and spaced by ky rather than by a loop of ours, and nothing here runs concurrently.
      retry: { limit: 3, methods: ["get"], statusCodes: [429, 500, 502, 503, 504] },
      throwHttpErrors: false,
      hooks: pauseMs ? { beforeRequest: [async () => void (await Bun.sleep(pauseMs))] } : {},
    });
  }

  /**
   * Perform one GET, returning whatever came back.
   *
   * An error response is a result, not an exception: the API rejecting a parameter is part of what
   * the agent has to deal with, and half of what one task measures. `throwHttpErrors` is off for
   * exactly that reason.
   */
  async get(path: string, params: Record<string, unknown> = {}): Promise<ApiResponse> {
    const url = new URL(`${this.baseUrl}${path}`);
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, Array.isArray(value) ? value.map(String).join(",") : String(value));
    }

    this.calls += 1;
    let response: Response;
    try {
      response = await this.client.get(url);
    } catch (error) {
      if (error instanceof HTTPError) response = error.response;
      else throw error;
    }

    const text = await response.text();
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      body = { _nonJsonBody: text };
    }
    return { status: response.status, body, url: url.toString(), ok: response.ok };
  }
}
