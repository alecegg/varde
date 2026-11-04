import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";

/**
 * Hold an OS-managed SQLite write lock until release or process death.
 * @param {string} storagePath
 */
export function acquireStorageFence(storagePath) {
  const db = new DatabaseSync(`${storagePath}.fence.sqlite`, { timeout: 0 });
  try {
    db.exec("PRAGMA journal_mode=DELETE; BEGIN EXCLUSIVE;");
  } catch (error) {
    db.close();
    throw error;
  }

  let released = false;
  return () => {
    if (released) return;
    released = true;
    try {
      db.exec("ROLLBACK");
    } finally {
      db.close();
    }
  };
}

/** @param {string} storagePath */
export async function prepareStoragePath(storagePath) {
  await mkdir(dirname(storagePath), { recursive: true });
}
