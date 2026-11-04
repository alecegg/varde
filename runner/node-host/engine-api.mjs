/** @typedef {{
 * emit: (event: string, session: string | null, data: object) => void,
 * log: (level: string, message: string) => void,
 * trackChild: (pid: number, pgid: number) => void,
 * untrackChild: (pgid: number) => void
 * }} EngineContext
 */

/** @typedef {{
 * name: string,
 * init: (ctx: EngineContext) => Promise<void>,
 * handle: (method: string, params: Record<string, unknown>, ctx: EngineContext) => Promise<object>,
 * shutdown: () => Promise<void>
 * }} Engine
 */

/**
 * Validate an engine module's public shape before it is exported to the host.
 * The host performs its own validation when loading arbitrary engine paths.
 *
 * @param {unknown} candidate
 * @returns {Engine}
 */
export function defineEngine(candidate) {
  if (candidate === null || typeof candidate !== "object") {
    throw new TypeError("engine must be an object");
  }
  const engine = /** @type {Partial<Engine>} */ (candidate);
  if (
    typeof engine.name !== "string" ||
    typeof engine.init !== "function" ||
    typeof engine.handle !== "function" ||
    typeof engine.shutdown !== "function"
  ) {
    throw new TypeError("engine needs name, init, handle, shutdown");
  }
  return /** @type {Engine} */ (engine);
}
