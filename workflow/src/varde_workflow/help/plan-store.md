Manage the SQLite plan state store

Usage: varde plan store <COMMAND> [OPTIONS]

Commands:
  status   Show mode, schema version and stored row counts
  migrate  Import Markdown state and switch to SQLite mode
  export   Write SQLite state back to Markdown
  import   Import Markdown queue and plan state
  backup   Create and verify a database backup
  restore  Restore a verified backup
  rollback Export state and switch back to Markdown mode
  verify   Compare stored state with Markdown

All commands accept --json. Commands that write accept --dry-run.
Migration backs up an existing database; rollback creates a fresh verified backup.
