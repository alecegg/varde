/**
 * Toolkit helpers for the token audit fixture set.
 * @param {string} owner
 * @returns {string}
 */
export function label(owner) {
  if (!owner) {
    return "unknown";
  }
  return `owner: ${owner}`;
}

export const summarize = (items, { limit = 10, upper = false } = {}) =>
  items
    .slice(0, limit)
    .map((item, index) => `${index}: ${upper ? item.toUpperCase() : item}`)
    .join(", ");

export class Cache {
  #entries = new Map();

  constructor(size = 32) {
    this.size = size;
  }

  get(key) {
    return this.#entries.get(key) ?? null;
  }

  set(key, value) {
    if (this.#entries.size >= this.size) {
      this.#entries.clear();
    }
    this.#entries.set(key, value);
    return this;
  }

  static empty() {
    return new Cache(0);
  }
}

export async function loadAll(sources, options = {}) {
  const results = [];
  for (const source of sources) {
    try {
      results.push(await load(source, options));
    } catch (error) {
      console.warn(`failed: ${source}`, error?.message);
    }
  }
  return results;
}

function load(source, { retries = 1 } = {}) {
  return Promise.resolve({ source, retries });
}
