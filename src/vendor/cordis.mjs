/**
 * Runtime re-export of the vendored harness's own cordis instance.
 *
 * The `#dsh/cordis` alias cannot point into the checkout directly: Node forbids
 * `node_modules` segments in package-`imports` targets. A relative re-export is
 * allowed, and routing through the harness's copy keeps one module instance —
 * a second cordis would carry its own service symbols and silently never match.
 * Types come from tsconfig `paths`, which has no such restriction.
 */
export * from "../../vendor/deepseek-harness/packages/core/agent/node_modules/@deepseek-ai/cordis/lib/index.js";
