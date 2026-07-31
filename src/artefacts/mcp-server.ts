#!/usr/bin/env bun
/**
 * The MCP arm's artefact: a real MCP server over stdio, generated from the registry.
 *
 * The arm is an installation, not a code path — a client points at this command and gets the
 * operations as tools. Schemas are built from the registry rather than written by hand, which is
 * what keeps the single-source-of-truth invariant alive across the move to a stock harness: what the
 * client sees is still generated from the same document the CLI is generated from.
 *
 *     bun run src/artefacts/mcp-server.ts                 # every operation, over stdio
 *     N_OPERATIONS=5 bun run src/artefacts/mcp-server.ts  # a slice, for cheap tests
 *     SHOW_SCHEMAS=1 bun run src/artefacts/mcp-server.ts  # print what a client would see
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import specDocument from "../../data/specs/camara-dados-abertos-v2.json";
import { Api } from "../api.ts";
import { applyFilter } from "../filter.ts";
import {
  isArrayParam,
  normalise,
  type Operation,
  type Param,
  type Registry,
  renderPath,
  sample,
} from "../spec.ts";

/** The projection parameter a server designed for agents would offer. */
export const FILTER_ARGUMENT = "filter";

/** JSON Schema for one parameter, derived from the registry rather than written per tool. */
export function propertySchema(param: Param): Record<string, unknown> {
  const scalar = (type: string): Record<string, unknown> => {
    const known = ["integer", "number", "boolean", "string"];
    return { type: known.includes(type) ? type : "string" };
  };
  const schema: Record<string, unknown> = isArrayParam(param)
    ? { type: "array", items: scalar(param.type.slice("array[".length, -1)) }
    : scalar(param.type);
  if (param.enum.length > 0) {
    if (schema.type === "array") (schema.items as Record<string, unknown>).enum = [...param.enum];
    else schema.enum = [...param.enum];
  }
  if (param.description) schema.description = param.description;
  if (param.default !== undefined) schema.default = param.default;
  return schema;
}

export function inputSchema(operation: Operation, filtering: boolean): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  for (const param of operation.params) properties[param.name] = propertySchema(param);
  if (filtering) {
    // Advertising the capability costs schema tokens on every tool. That is the honest price of
    // having it, and it is part of what the comparison measures.
    properties[FILTER_ARGUMENT] = {
      type: "string",
      description:
        "Optional jq expression applied to the response before it is returned, e.g. '.dados|length'. " +
        "Use it to avoid returning fields you do not need.",
    };
  }
  const required = operation.params.filter((p) => p.required).map((p) => p.name);
  return { type: "object", properties, ...(required.length > 0 ? { required } : {}) };
}

export function toolDescription(operation: Operation): string {
  return [operation.summary, operation.description].filter(Boolean).join("\n\n");
}

export function toolDefinitions(registry: Registry, filtering: boolean): Record<string, unknown>[] {
  return registry.operations.map((operation) => ({
    name: operation.name,
    description: toolDescription(operation),
    inputSchema: inputSchema(operation, filtering),
  }));
}

/**
 * Build the server over the protocol's low-level API.
 *
 * `McpServer.registerTool` wants a Zod shape; the schemas here come from the registry as JSON
 * Schema, and converting them to Zod and back would put a translation layer between the source of
 * truth and what the client sees. Serving `tools/list` directly keeps that path short enough to
 * verify by eye.
 */
export function createServer(registry: Registry, api: Api, filtering: boolean): Server {
  const server = new Server(
    { name: "camara", version: registry.version || "1" },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: toolDefinitions(registry, filtering),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const operation = registry.operations.find((op) => op.name === request.params.name);
    if (!operation) throw new Error(`unknown tool: ${request.params.name}`);
    const args = (request.params.arguments ?? {}) as Record<string, unknown>;

    const filter = filtering ? (args[FILTER_ARGUMENT] as string | undefined) : undefined;
    const pathValues: Record<string, unknown> = {};
    const query: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(args)) {
      if (key === FILTER_ARGUMENT || value === undefined || value === null || value === "") continue;
      const param = operation.params.find((p) => p.name === key);
      if (param?.location === "path") pathValues[key] = value;
      else query[key] = value;
    }
    const response = await api.get(renderPath(operation, pathValues), query);
    const text = filter ? await applyFilter(response.body, filter) : JSON.stringify(response.body);
    return { content: [{ type: "text" as const, text }] };
  });

  return server;
}

if (import.meta.main) {
  let registry = await normalise(specDocument);
  const limit = process.env.N_OPERATIONS;
  if (limit) registry = sample(registry, Number(limit), { seed: 0 });
  const filtering = process.env.FILTERING === "1";

  if (process.env.SHOW_SCHEMAS) {
    process.stdout.write(`${JSON.stringify(toolDefinitions(registry, filtering), null, 2)}\n`);
  } else {
    const api = new Api(registry.baseUrl);
    process.stderr.write(`camara: ${registry.operations.length} operations\n`);
    await createServer(registry, api, filtering).connect(new StdioServerTransport());
  }
}
