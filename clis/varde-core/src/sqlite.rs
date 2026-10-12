//! SQLite connection setup shared by the toz and learn stores.

use std::time::Duration;

use rusqlite::Connection;

/// Wait up to 30 s on locks, then enable WAL, `synchronous=NORMAL`, and foreign keys.
pub fn configure_connection(conn: &Connection) -> rusqlite::Result<()> {
    conn.busy_timeout(Duration::from_secs(30))?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "NORMAL")?;
    conn.pragma_update(None, "foreign_keys", "ON")
}
