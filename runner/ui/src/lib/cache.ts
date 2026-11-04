const VERSION = 1;

export function cacheWrite(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify({ version: VERSION, savedAt: Date.now(), value }));
  } catch {
    // Storage is an optional rendering cache; localStorage survives an iPhone web-app relaunch.
  }
}

/** The cached value, or null when missing, from another version, or older than maxAgeMs. */
export function cacheRead<T>(key: string, maxAgeMs: number): T | null {
  try {
    const entry = JSON.parse(localStorage.getItem(key) ?? 'null');
    if (entry?.version !== VERSION || !(Date.now() - entry.savedAt <= maxAgeMs)) return null;
    return entry.value as T;
  } catch {
    return null;
  }
}
