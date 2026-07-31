/**
 * Normalise an OpenAPI 3 document into the operation registry that every artefact is generated from.
 *
 * This is the single source of truth of the experiment. The MCP server and the CLI are both emitted
 * from it, so a behavioural difference between arms is always a difference of *exposure* and never
 * of capability. Nothing here knows about MCP, about CLIs, or about token counting.
 */

import { dereference, validate } from "@readme/openapi-parser";
import { uniformInt } from "pure-rand/distribution/uniformInt";
import { xoroshiro128plus } from "pure-rand/generator/xoroshiro128plus";

const HTTP_METHODS = ["get", "post", "put", "patch", "delete", "head", "options"] as const;

const WRITE_VERBS: Record<string, string> = {
  POST: "create",
  PUT: "update",
  PATCH: "update",
  DELETE: "delete",
};

export type ParamLocation = "query" | "path" | "header" | "cookie";

/** A single input to an operation, described independently of how it is later exposed. */
export interface Param {
  readonly name: string;
  readonly location: ParamLocation;
  readonly required: boolean;
  readonly type: string;
  readonly description: string;
  readonly enum: readonly string[];
  readonly default: string | undefined;
}

export function isArrayParam(param: Param): boolean {
  return param.type.startsWith("array");
}

/** One callable capability: an HTTP operation stripped of its transport details. */
export interface Operation {
  /** Derived by `toolName`. This is what the agent sees, in every arm. */
  readonly name: string;
  /** The spec's own `operationId`, kept only so findings can be traced back to the source. */
  readonly id: string;
  readonly method: string;
  readonly path: string;
  readonly group: string;
  readonly summary: string;
  readonly description: string;
  readonly params: readonly Param[];
}

export function requiredParams(operation: Operation): readonly Param[] {
  return operation.params.filter((p) => p.required);
}

/** Substitute path parameters, leaving query parameters to the caller. */
export function renderPath(operation: Operation, values: Record<string, unknown>): string {
  let path = operation.path;
  for (const param of operation.params) {
    if (param.location !== "path") continue;
    if (!(param.name in values)) {
      throw new Error(`${operation.id}: missing path parameter '${param.name}'`);
    }
    path = path.replaceAll(`{${param.name}}`, String(values[param.name]));
  }
  return path;
}

/**
 * Derive a stable, readable name for an operation from its method and route.
 *
 * Real specs cannot be trusted to name things usefully: the vendored one calls two unrelated
 * listings `listar` and `listar_1`, and a bare `search`. Those names would handicap the agent, so
 * every arm gets names from this transform instead — mechanically, identically, and without touching
 * the spec. Only the verb is imposed; the resource nouns stay exactly as the API spells them,
 * because they are domain vocabulary rather than something we are free to translate.
 */
export function toolName(method: string, path: string): string {
  const segments = path.split("/").filter((s) => s.length > 0);
  const concrete = segments.filter((s) => !(s.startsWith("{") && s.endsWith("}")));
  const last = segments.at(-1);

  let verb: string;
  if (method.toUpperCase() === "GET") {
    verb = last?.startsWith("{") ? "get" : "list";
  } else {
    verb = WRITE_VERBS[method.toUpperCase()] ?? method.toLowerCase();
  }

  const noun = concrete
    .map((s) =>
      s
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, ""),
    )
    .join("_");
  return noun ? `${verb}_${noun}` : verb;
}

export interface Registry {
  readonly title: string;
  readonly version: string;
  readonly baseUrl: string;
  readonly operations: readonly Operation[];
}

export function byName(registry: Registry, name: string): Operation {
  const found = registry.operations.find((op) => op.name === name);
  if (!found) throw new Error(`unknown operation: '${name}'`);
  return found;
}

/** Look an operation up by the spec's original `operationId`. */
export function byId(registry: Registry, operationId: string): Operation {
  const found = registry.operations.find((op) => op.id === operationId);
  if (!found) throw new Error(`unknown operationId: '${operationId}'`);
  return found;
}

/**
 * Operations bucketed by their OpenAPI tag.
 *
 * Groups stand in for separate MCP servers: connecting six servers is the situation the context cost
 * of MCP is usually complained about, and tags are the spec's own partition.
 */
export function groups(registry: Registry): Map<string, Operation[]> {
  const out = new Map<string, Operation[]>();
  for (const op of registry.operations) {
    const bucket = out.get(op.group);
    if (bucket) bucket.push(op);
    else out.set(op.group, [op]);
  }
  return new Map([...out.entries()].sort(([a], [b]) => a.localeCompare(b)));
}

/**
 * Deterministically narrow the registry to `n` operations for the N-scaling axis.
 *
 * Operations named in `keep` are always included — the tasks have to stay solvable as N shrinks,
 * otherwise a small-N arm looks efficient only because it was handed an impossible job. The
 * remainder is drawn with a seeded generator, and the result keeps the registry's original ordering
 * so token counts do not wobble between runs.
 */
export function sample(
  registry: Registry,
  n: number,
  options: { keep?: readonly string[]; seed?: number } = {},
): Registry {
  const { keep = [], seed = 0 } = options;
  if (n > registry.operations.length) {
    throw new Error(`cannot sample ${n} of ${registry.operations.length} operations`);
  }
  const kept = keep.map((name) => byName(registry, name));
  if (kept.length > n) {
    throw new Error(`keep= names ${kept.length} operations, more than n=${n}`);
  }

  const keptNames = new Set(kept.map((op) => op.name));
  const pool = registry.operations
    .filter((op) => !keptNames.has(op.name))
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name));

  const random = xoroshiro128plus(seed);
  const drawn: string[] = [];
  const available = pool.slice();
  while (drawn.length < n - kept.length) {
    const [picked] = available.splice(uniformInt(random, 0, available.length - 1), 1);
    if (picked) drawn.push(picked.name);
  }

  const chosen = new Set([...keptNames, ...drawn]);
  return {
    title: registry.title,
    version: registry.version,
    baseUrl: registry.baseUrl,
    operations: registry.operations.filter((op) => chosen.has(op.name)),
  };
}

type Json = Record<string, unknown>;

function paramType(schema: Json): string {
  const kind = typeof schema.type === "string" ? schema.type : "string";
  if (kind === "array") {
    const items = (schema.items ?? {}) as Json;
    return `array[${typeof items.type === "string" ? items.type : "string"}]`;
  }
  return kind;
}

function paramEnum(schema: Json): string[] {
  if (Array.isArray(schema.enum)) return schema.enum.map(String);
  if (schema.type === "array") {
    const items = (schema.items ?? {}) as Json;
    if (Array.isArray(items.enum)) return items.enum.map(String);
  }
  return [];
}

function readParams(operation: Json, dropTransportParams: boolean): Param[] {
  const raw = Array.isArray(operation.parameters) ? operation.parameters : [];
  const params: Param[] = [];
  for (const entry of raw) {
    const p = entry as Json;
    const location = (typeof p.in === "string" ? p.in : "query") as ParamLocation;
    if (dropTransportParams && (location === "header" || location === "cookie")) continue;
    const schema = (p.schema ?? {}) as Json;
    const fallback = schema.default;
    params.push({
      name: String(p.name),
      location,
      required: p.required === true,
      type: paramType(schema),
      description: String(p.description ?? "").trim(),
      enum: paramEnum(schema),
      default: fallback === undefined || fallback === null ? undefined : String(fallback),
    });
  }
  return params;
}

/**
 * Build a `Registry` from an OpenAPI 3 document whose `$ref`s are already resolved.
 *
 * `dropTransportParams` hides header and cookie parameters. The vendored spec declares an `Accept`
 * header on all 78 operations, and exposing it would let the agent ask for XML and break response
 * parsing for reasons that have nothing to do with the comparison. The harness pins those headers
 * instead. The filter runs here, once, so every arm is guaranteed to inherit it.
 */
export function fromOpenApi(
  doc: Json,
  options: { baseUrl?: string; dropTransportParams?: boolean } = {},
): Registry {
  const { baseUrl, dropTransportParams = true } = options;
  const version = String(doc.openapi ?? "");
  if (!version.startsWith("3.")) {
    throw new Error(`expected OpenAPI 3.x, got ${JSON.stringify(version)}`);
  }

  const servers = Array.isArray(doc.servers) && doc.servers.length > 0 ? doc.servers : [{}];
  const firstServer = (servers[0] ?? {}) as Json;
  const resolvedBase = (baseUrl ?? String(firstServer.url ?? "")).replace(/\/+$/, "");

  const operations: Operation[] = [];
  const paths = (doc.paths ?? {}) as Record<string, Json>;
  for (const [path, item] of Object.entries(paths)) {
    const shared = Array.isArray(item.parameters) ? item.parameters : [];
    for (const method of HTTP_METHODS) {
      const raw = item[method];
      if (!raw || typeof raw !== "object") continue;
      const op = { ...(raw as Json) };
      op.parameters = [...shared, ...(Array.isArray(op.parameters) ? op.parameters : [])];
      const tags = Array.isArray(op.tags) && op.tags.length > 0 ? op.tags : ["default"];
      operations.push({
        name: toolName(method, path),
        id: String(op.operationId ?? `${method}_${path}`),
        method: method.toUpperCase(),
        path,
        group: String(tags[0]),
        summary: String(op.summary ?? "").trim(),
        description: String(op.description ?? "").trim(),
        params: readParams(op, dropTransportParams),
      });
    }
  }

  const names = operations.map((op) => op.name);
  const clashes = [...new Set(names.filter((n) => names.filter((m) => m === n).length > 1))].sort();
  if (clashes.length > 0) {
    throw new Error(`derived tool names are not unique: ${clashes.join(", ")}`);
  }

  const info = (doc.info ?? {}) as Json;
  return {
    title: String(info.title ?? "api"),
    version: String(info.version ?? ""),
    baseUrl: resolvedBase,
    operations,
  };
}

export interface ValidationReport {
  readonly valid: boolean;
  readonly errors: readonly string[];
}

/**
 * Resolve `$ref`s and build a registry.
 *
 * Dereferencing is delegated to `@readme/openapi-parser` rather than hand-rolled. It also handles
 * external files and circular references, neither of which this spec uses today and both of which a
 * different spec might.
 */
export async function normalise(
  doc: unknown,
  options: { baseUrl?: string; dropTransportParams?: boolean } = {},
): Promise<Registry> {
  const resolved = (await dereference(structuredClone(doc) as never)) as Json;
  return fromOpenApi(resolved, options);
}

/**
 * Check a document against the OpenAPI schema, without refusing to load it.
 *
 * The vendored spec does not validate — it carries one enum violation on a query parameter. That is
 * a fact about the subject, not a reason to abandon the experiment, so validity is reported and the
 * document is used regardless. Refusing here would be refusing the only API the benchmark has.
 */
export async function check(path: string): Promise<ValidationReport> {
  const report = (await validate(path)) as { valid: boolean; errors?: { message?: string }[] };
  return {
    valid: report.valid,
    errors: (report.errors ?? []).map((e) => (e.message ?? "").split(/\r?\n/)[0] ?? ""),
  };
}

/** Load a vendored OpenAPI document from disk. */
export async function load(
  path: string,
  options: { baseUrl?: string; dropTransportParams?: boolean } = {},
): Promise<Registry> {
  return normalise(await Bun.file(path).json(), options);
}
