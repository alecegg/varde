import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";

export async function openApprovalStore(path) {
  await mkdir(dirname(path), { recursive: true });
  const db = new DatabaseSync(path);
  db.exec(`
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS approvals (
      key TEXT PRIMARY KEY,
      tool TEXT NOT NULL,
      summary TEXT NOT NULL,
      input_json TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','expired')),
      created_at INTEGER NOT NULL,
      answered_at INTEGER
    );
    CREATE TABLE IF NOT EXISTS deliveries (
      key TEXT PRIMARY KEY,
      status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
      value_json TEXT,
      error TEXT,
      created_at INTEGER NOT NULL,
      completed_at INTEGER
    );
  `);
  const getApproval = db.prepare("SELECT * FROM approvals WHERE key = ?");
  const insertApproval = db.prepare(
    "INSERT OR IGNORE INTO approvals(key, tool, summary, input_json, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
  );
  const respond = db.prepare(
    "UPDATE approvals SET status = ?, answered_at = ? WHERE key = ? AND status = 'pending'",
  );
  const getDelivery = db.prepare("SELECT * FROM deliveries WHERE key = ?");
  const insertDelivery = db.prepare(
    "INSERT OR IGNORE INTO deliveries(key, status, created_at) VALUES (?, 'running', ?)",
  );
  const completeDelivery = db.prepare(
    "UPDATE deliveries SET status = 'completed', value_json = ?, completed_at = ? WHERE key = ? AND status = 'running'",
  );
  const failDelivery = db.prepare(
    "UPDATE deliveries SET status = 'failed', error = ?, completed_at = ? WHERE key = ? AND status = 'running'",
  );

  return {
    ensurePending({ key, tool, summary, input }) {
      const inputJson = JSON.stringify(input);
      insertApproval.run(key, tool, summary, inputJson, Date.now());
      const row = getApproval.get(key);
      if (row.tool !== tool || row.summary !== summary || row.input_json !== inputJson) {
        throw new Error(`approval key reused with different request data: ${key}`);
      }
      return { ...row, input: JSON.parse(row.input_json) };
    },
    get(key) {
      const row = getApproval.get(key);
      return row ? { ...row, input: JSON.parse(row.input_json) } : undefined;
    },
    respond(key, decision, answeredAt) {
      return Number(respond.run(decision, answeredAt, key).changes) === 1;
    },
    beginDelivery(key) {
      db.exec("BEGIN IMMEDIATE");
      try {
        const inserted = insertDelivery.run(key, Date.now());
        const row = getDelivery.get(key);
        db.exec("COMMIT");
        return {
          claimed: Number(inserted.changes) === 1,
          status: row.status,
          value: row.value_json === null ? undefined : JSON.parse(row.value_json),
        };
      } catch (error) {
        db.exec("ROLLBACK");
        throw error;
      }
    },
    completeDelivery(key, value) {
      const result = completeDelivery.run(JSON.stringify(value), Date.now(), key);
      if (Number(result.changes) !== 1) throw new Error(`delivery is no longer running: ${key}`);
    },
    failDelivery(key, error) {
      failDelivery.run(error, Date.now(), key);
    },
    close() {
      db.close();
    },
  };
}
