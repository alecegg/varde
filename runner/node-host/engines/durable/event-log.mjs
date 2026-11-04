import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";

export async function openEventLog(path) {
  await mkdir(dirname(path), { recursive: true });
  const db = new DatabaseSync(path);
  db.exec(`
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS events (
      cursor INTEGER PRIMARY KEY,
      conversation_id TEXT NOT NULL,
      entry_id TEXT NOT NULL,
      ordinal INTEGER NOT NULL,
      event_json TEXT NOT NULL,
      UNIQUE(conversation_id, entry_id, ordinal)
    );
  `);
  const findEvent = db.prepare(
    "SELECT cursor FROM events WHERE conversation_id = ? AND entry_id = ? AND ordinal = ?",
  );
  const maxCursor = db.prepare("SELECT COALESCE(MAX(cursor), 0) AS cursor FROM events");
  const insert = db.prepare(
    "INSERT INTO events(cursor, conversation_id, entry_id, ordinal, event_json) VALUES (?, ?, ?, ?, ?)",
  );
  const read = db.prepare(
    "SELECT cursor, event_json FROM events WHERE conversation_id = ? AND cursor > ? ORDER BY cursor",
  );
  const usageRows = db.prepare(
    "SELECT event_json FROM events WHERE conversation_id = ? AND json_extract(event_json, '$.type') = 'usage' ORDER BY cursor",
  );

  return {
    append(conversationId, events) {
      db.exec("BEGIN IMMEDIATE");
      try {
        let cursor = Number(maxCursor.get().cursor);
        let index = 0;
        while (index < events.length) {
          const entryId = String(events[index].entryId);
          let ordinal = 0;
          while (index < events.length && String(events[index].entryId) === entryId) {
            const event = events[index];
            if (!findEvent.get(conversationId, entryId, ordinal)) {
              cursor += 1;
              insert.run(cursor, conversationId, entryId, ordinal, JSON.stringify(event));
            }
            ordinal += 1;
            index += 1;
          }
        }
        db.exec("COMMIT");
        return cursor;
      } catch (error) {
        db.exec("ROLLBACK");
        throw error;
      }
    },
    readFrom(conversationId, cursor) {
      return read.all(conversationId, cursor).map((row) => ({
        cursor: Number(row.cursor),
        event: JSON.parse(row.event_json),
      }));
    },
    usage(conversationId) {
      const totals = new Map();
      for (const row of usageRows.all(conversationId)) {
        const event = JSON.parse(row.event_json);
        const key = `${event.provider}/${event.model}`;
        const total = totals.get(key) ?? {
          provider: event.provider,
          model: event.model,
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          costUsd: 0,
        };
        for (const key of ["input", "output", "cacheRead", "cacheWrite", "totalTokens"]) {
          total[key] += Number(event.usage[key] ?? 0);
        }
        total.costUsd += Number(event.costUsd ?? 0);
        totals.set(key, total);
      }
      return [...totals.values()];
    },
    close() {
      db.close();
    },
  };
}
