# Data API

`varde-data` provides shared storage contracts and helpers. Domain backends
remain private; callers should use the public symbols below.

## Errors

Import errors from `varde_data.errors`; common errors are also re-exported from
`varde_data`:

| Name | Purpose |
| --- | --- |
| `DataError` | Base error for the data layer. |
| `NotFound` | Requested data does not exist. |
| `Invalid` | Requested data is invalid. |
| `Conflict` | Requested change conflicts with current data. |
| `Locked` | Another operation holds the requested data lock. |
| `WrongMode` | The requested store operation is unavailable in the active mode. |

## Locking and durable files

`varde_data.locking` exposes `file_lock(path, *, timeout)`,
`atomic_write(path, data, *, mode)`, `atomic_write_unsynced(path, data, *, mode)`,
`append_line(path, line, *, lock_path)`, `read_complete_lines(path)`, and
`remove_stale_temps(directory, older_than)`. Use the established lock paths
when integrating a store:

| Store | Lock path |
| --- | --- |
| Friction | `friction.jsonl` itself. |
| Inbox | `.<reader>.lock`. |
| Relay | `relay/.lock`. |
| Binding | Per-address directory. |
| Queue order | `.queue-order.json.lock`. |
| Message log appends | `.cache/inbox/.messages.lock`. |
| Concluded message state | `.cache/inbox/.state.lock`. |
| Message store mode | `.cache/inbox/store-mode.lock` (shared for repository selection; exclusive for transitions). |
| Mirror writes and cutover | `.cache/inbox/mirror.lock`. |
| Binding events | `.cache/inbox/.events.lock` (nested after the per-address lock). |
| Address slots | `.cache/inbox/slots/.lock`. |
| Plan Markdown writers | `plans/<plan>/.plan.lock` (5 second timeout). |
| Queue store operations | `.queue.mode.lock` (shared); migration and rollback hold it exclusively. |

Stores without an established lock use a sibling `.lock` file.

## Versions and cursors

`varde_data.version` exposes `Version`, `Cursor`, and
`files_version(paths, *, file_set_root=None)`. `Version.is_racy_at(timestamp_ns)`
identifies source mtimes within two seconds of the supplied timestamp.

## Read cache

`varde_data.cache` exposes `CachedData(load, version, *, clock_ns=time.time_ns)`;
call `get()` to reuse a result while its source version is stable. It also
exposes `UnstableDataError`, raised after three attempts observe changing data.

## Configuration

`varde_data.config` exposes `DataConfig(backends={})` and
`load_data_config(config_dir=None)`. Configuration is read from `data.toml`;
`VARDE_DATA_<DOMAIN>_BACKEND` environment variables override individual domains.

## Opening domains

`varde_data.open` exposes `DomainRegistration`, `DOMAIN_REGISTRY`, `Data`,
`open_data(working_dir, config)`, and `check_schema_version(path, supported)`.
Register domains in `DOMAIN_REGISTRY`; `open_data` returns a lazy `Data` handle
that imports a registered domain on first attribute access.

`varde_data.paths` exposes `data_dir()`, which returns the platform data
directory or `None`.

## Plans

`varde_data.records.plans` exposes frozen `PlanRecord`, `TaskRecord`, and
`ReadResult` records. Raw Markdown bytes and parsed/extra frontmatter are kept
for later compare-and-swap writes. Record `path` is an opaque display value and
must not be used for backend I/O. Plan records include skipped task counts,
source mtime, review verdict, and archive membership. Standalone `task.md`
artifacts are returned with `artifact_type="task"`. Typed `status`, `title`,
`owner`, and `assigned_to` accessors return strings or `None`; `depends_on`
returns a tuple of string dependencies, filtering malformed entries.

`varde_data.repos.plans` exposes the `PlanRepositoryReader` protocol and
`resolve_plan_ref`. The reader supports `list`, `get`, `owner_lookup`, and
`version`. File-backed `get` resolves references in this
order: frontmatter `id`, plan directory basename, then a matching date suffix.
It scans frontmatter heads for each tier and fully parses only the winner.
Discovery skips a directory named `tasks` directly inside a plan directory,
because those task files are loaded from the plan record. It still discovers
nested plan or task documents under other directories such as `notes/`.
Successful `get` calls clean stale temporary files only in the selected
record's directory; lookup does not write to the other scanned directories.
`FilesPlans.get_by_path` accepts a caller-resolved Markdown file inside the
configured plans root. Missing, outside-root, and unparseable paths raise
`NotFound`; plan results include their review verdict and tasks. Archive plans
are excluded from `get` unless `include_archived=True`.

`PlanRepositoryReader` also exposes `set_task_status`, `set_owner`,
`set_assigned_to`, `set_merge_approved_at`, `set_plan_status`, and
`replace_body`. Writers accept the record previously read and compare its raw
bytes under the per-plan lock. A mismatch raises `Conflict`; lock timeout raises
`Locked`. Hand edits do not take the plan lock, so a hand edit after the final
compare and before `os.replace` can still be overwritten. Field writers preserve
unrelated bytes, and file writes preserve the existing mode with an atomic
replacement. The returned record is parsed from the changed file only. Task
status transitions and `status_at` are supplied by the caller. `MemoryPlans`
implements these methods for contract tests.

### File-backed plans index

Each `FilesPlans` instance owns a thread-safe, in-memory index. It is not
persistent; callers that need to share cached reads and version tokens should
share one repository instance per working directory. The runner does this
within each process.

`version()` is an equality-only token over the mtimes of discovered directories
and stat keys for reader artifacts: `plan.md`, `task.md`, `review.md`, and
`tasks/*.md`. An artifact stat key is `(mtime_ns, ctime_ns, size, inode)`.
Directory mtimes cover membership changes; artifact stat keys cover the files
whose contents can affect reader results. Editing non-artifact notes, comments,
or other auxiliary files does not invalidate the token. Creating or removing an
entry can change its containing directory's mtime, and nested Markdown reader
artifacts remain included wherever discovery finds them.

Directory scan, byte, and parsed-field cache entries are checked against their
load time. If an artifact mtime is within two seconds of that load time,
including a future mtime, the entry is treated as racy and is scanned or read
again instead of trusted. `Version.is_racy_at(timestamp_ns)` marks token mtimes
within two seconds on either side of the supplied timestamp.

### SQLite plans read index

`varde_data.plans` exposes `open_fresh_plans(working_dir)` (refreshes inline)
and `open_indexed_plans(working_dir)` (opens the published snapshot as-is).
Both return `SqlitePlans`; its writes delegate to `FilesPlans` and refresh
afterward. `refresh()` updates the index, and `version()` returns its generation.

Lightweight readers can query row dictionaries without creating
`PlanRecord` objects:

- Plans and tasks: `plan_rows()`, `task_rows(plan_path=None)`.
- Review and auxiliary facts: `review_rows()`, `task_note_rows()`,
  `now_line_rows()`, `invalid_rows()`, `activity_rows()`.
- Combined views: `status_rows()`, `watch_rows()`.

The runbook documents schema, freshness, rollback, health, sandbox, and measured
runner behavior: [plans read index](../docs/plans-read-index.md).

## Queue store

`varde_data.records.queue` exposes frozen `QueueItemInput`, `QueueItem`,
`QueueEvent`, `CycleTime`, `PlanState`, and `TaskState` records.
`varde_data.repos.queue.QueueRepository` defines the backend-neutral queue API:
`version()` returns an equality-only `Version` token for queue, plan, and task
state changes;
`enqueue` is idempotent by queue and item id; `list` orders by priority then
row order; `get` raises `NotFound`; and `transition` checks optional expected
state and generation, raising `Conflict` on mismatch. Matching lifecycle
timestamps are set once.

`claim` atomically takes the first ready queued item, returns `None` when none
is ready, and records a lease owner, expiry, incremented generation, and
optional epoch. `renew`, `renew_all`, `release`, and `expire` support optional
fences. A lost lease raises `Conflict`; `expire(workers=...)` can limit expiry
to named workers. Fences run before writes in the operation's transaction;
the memory backend passes `None` as the connection. Claim readiness receives
the in-flight items. `events` returns the event history and `cycle_times`
returns planned-to-merged and build-duration values. Plan and task state are
read and written with `plan_state`, `task_states`, `set_plan_state`, and
`set_task_state`.

Open the repository through `open_data(...).queue` or
`varde_data.queue.open_queue(working, backend_name="sqlite")`. The SQLite
database is `<working>/.cache/data/queue.sqlite3`; `memory` is available for
ephemeral use. Queue repository calls acquire the shared mode lock. In
markdown mode they raise `WrongMode`, allowing callers to take the legacy path
while their surrounding `operation(working)` remains active. `WrongMode` is
available from `varde_data.errors`.
`operation(working)` yields the active store mode under a shared lock;
`barrier(working, timeout)` holds the exclusive mode lock for migrations.

## Slots

A durable slot records the stable, named holder of a plan role
(`<plan-id>-<role>`, or `orchestrator-<n>`): its agent and session refs, epoch,
starting lease, progress, context use, and handoff checkpoint. Claims are owned
by the slot id, not the agent: `claim`, `release`, and `finish` write
`queue_items.claimed_by = slot_id` and keep the epoch separately in
`claim_epoch`. A replacement therefore inherits the claimed items without
releasing them, so no other worker can take them in between.

`varde_data.repos.slots` exposes the `SlotRepository` protocol and
`ReclaimReport`; `varde_data.slot_model` exposes the `Slot` and `SlotEvent`
records with `SlotState`, `SLOT_STATES`, `epoch_matches`, `is_stale`, and
`next_state`; `varde_data.slot_handoff` exposes `build_handoff_record`. Open the
repository through `open_data(...).slots` or
`varde_data.queue.open_slots(working, backend_name="sqlite")`. It is store-only
and shares the queue database, `<working>/.cache/data/queue.sqlite3`; in
markdown mode every call raises `WrongMode`.

- `register(slot_id, *, plan_id, role, agent_ref, session_id=None, lease_s=300)`
  creates an active slot at epoch 1. Repeating it for the same plan, role, and
  agent ref on a live slot returns the slot; a different ref raises `Conflict`
  (use `replace`).
- `heartbeat(slot_id, *, epoch, progress_note=None, context_tokens=None,
  turn_count=None, lease_s=None, now=None)` records progress and renews every
  claimed item in one transaction.
- `claim(slot_id, *, epoch, queue_name, lease_s, now=None, ready=None)` takes the
  first ready item with `worker=slot_id`; `release(...)` returns one item to a
  chosen state, and `finish(...)` completes it with an optional follow-up.
- `claimed(slot_id)` lists the items whose state is `claimed`, `building`, or
  `in_review`.
- `replace(slot_id, *, new_agent_ref, new_session_id=None, lease_s=None,
  actor="system", now=None)` increments the epoch, activates the slot, rewrites
  `claim_epoch` on its claimed items, and renews their leases.
- `park(slot_id, *, epoch, now=None)` and `unpark(slot_id, *, epoch,
  lease_s=None, now=None)` change state as described below.
- `reclaim_stale(now=None)` returns a `ReclaimReport` of reclaimed ids, skipped
  ids, and expired items.
- `handoff(slot_id, *, epoch, checkpoint, now=None)` stores the checkpoint and
  sets the slot to `handed_off`. `handoff_record(slot_id)` builds the plain-data
  checkpoint: role, slot, plan id, epoch, claimed items, last progress, context
  tokens, the last 20 events, task states, and next actions.
- `show`, `events`, and `by_session` read one slot, its events in `seq` order,
  or the session's slot, preferring active, then parked, handed_off, and dead
  states.

Callers pass the `epoch` they registered or resumed with. A fence reads
`slots.epoch` and `slots.state` inside the queue operation's own transaction and
raises `Conflict` when the epoch is stale or the slot is dead. `replace` reads
the current epoch and commits the next one under `BEGIN IMMEDIATE` in the same
database, so no interleaving lets a previous agent's heartbeat, claim, release,
finish, park, unpark, or handoff succeed. A dead slot also rejects those calls.

`park` sets the state to `parked` and renews every claimed item to the 4-hour
park lease, so an idle reaper leaves the claims intact for a resumed session. A
parked slot is reclaimed only after the park lease lapses from its last update;
`unpark` returns it to `active` and renews the claims with the supplied lease.
`unpark` on a slot that was reclaimed in the meantime raises `Conflict`.

`reclaim_stale` finds candidates with a read, then re-checks each one for
staleness inside the `queue.expire` transaction. A slot that became live through
a heartbeat, unpark, or replace raises `Conflict`, is caught, and is reported as
skipped. A stale slot is marked `dead` with `dead` and `reclaim` events, and its
lapsed items return to `queued` with a bumped generation through
`expire(workers=[slot_id])`; other workers' claims are untouched.

`slot_events` stores `seq`, slot id, timestamp, actor, kind, epoch, and sorted
JSON detail. Event kinds are `register`, `heartbeat`, `replace`, `park`,
`unpark`, `handoff`, `dead`, and `reclaim`; `replace` details the old and new
agent refs, `handoff` marks a stored checkpoint, and reclaim events carry the
reason.

## Messages

`varde_data.records.messages` exposes message, delivery, cursor, and status
records. `varde_data.repos.messages` exposes the backend-neutral
`MessageRepository` protocol. Open it through `open_data(...).messages` or
`varde_data.messages.open_messages(working, backend, *, resolver=None,
busy_timeout=30)`; callers should not construct a backend directly. Supported
backends are `files`, `sqlite`, `mirror-files`, `mirror-sqlite`, and `memory`.

`messages_db_path(working)` returns `<working>/.cache/inbox/messages.sqlite3`;
`message_store_files(working)` returns that database plus its `-wal` and `-shm`
files. SQLite uses WAL and `synchronous=FULL` on each repository connection.
Schema version 3 is stored in `PRAGMA user_version`; opening an unversioned
database creates the schema, while a newer version raises `Invalid`. A busy
database or lock timeout raises `Locked`. An unwritable or read-only inbox raises
`Invalid` with a request to grant write access to `.cache/inbox`.
The claim path uses a reader/message/event delivery index to check suppression
without materializing the delivery log.

The per-working-directory mode marker is `.cache/inbox/store-mode.json` and is
cross-checked against `meta.store_mode` in the database. Once present, that
marker selects the backend mode regardless of the host backend setting. The
valid adjacent transition path is `files` -> `mirror-files` -> `mirror-sqlite` ->
`sqlite`;
`mirror-files` writes files first and mirrors to SQLite, while `mirror-sqlite`
writes SQLite first and mirrors to files. `set_store_mode(working, mode)` takes
the exclusive mode lock. A transition out of a mirrored mode drains pending
rows and verifies both stores before changing the marker and database metadata;
transitions from an unmirrored mode have no existing mirror to verify.
Repository selection holds the shared mode lock, bounded by `busy_timeout`; the
prompt hook supplies 2 seconds. Mirror writes hold that shared lock through the
write. The lock timeout raises `Locked`.

The SQLite repository implements `import_messages`, `import_reader_position`,
`import_deliveries`, and `import_concluded` for replay. The mirror wrapper uses
these methods to resume by persisted message and delivery positions. `sync()`
replays pending streams; `compare()` checks full state and records parity events;
`parity_report()` returns recent counts. These are repository methods, not CLI
store-mode commands.

The workflow CLI supports these transfer commands (the defaults shown are
`--from files --to sqlite`):

- `varde msg store import`: replay files into SQLite and mark the import
  verified when the report has no mismatches. The report also exposes skipped
  rows and torn tails; operators should require both to be zero.
- `varde msg store sync [--from {files,sqlite}] [--to {files,sqlite}]`: replay one
  store into the other. Use `--from sqlite --to files` to refresh the rollback
  copy.
- `varde msg store verify [--from {files,sqlite}] [--to {files,sqlite}]`: compare
  stores without creating or modifying them. `--repair-mode` repairs one
  interrupted marker/database mode write. It adopts a DB-only `files/none`
  record; other DB-only modes require `--repair-mode --force-adopt` after
  confirming the intended mode.
- `varde msg store export --dest PATH`: write a files-format copy outside the
  live working tree; the destination inbox must be empty.

The CLI parser accepts those actions and flags. It currently has no command to
change store mode; use `set_store_mode` from `varde_data.store_mode` for the
adjacent transitions above.

`append` returns the stored message. `read_all`, `read_since`, `peek_unread`,
`deliveries`, `status_events`, `status`, `version`, and `concluded_addresses`
are read-only and do not lock or write. `read_since` accepts an opaque ordered `Cursor`
and returns records plus `skipped`, a tuple of diagnostic strings for
invalid records. `head` returns the current cursor. Cursor values
are backend-specific opaque tokens; file byte offsets are an implementation
detail.

`unread` and `claim_unread` may seed a reader index and take that reader's lock.
`claim_unread` also records delivery events. A first-contact reader starts at
the current end unless registered from the beginning. Unread and acknowledgement
are determined by the reader resolved from each message's recipient address;
acknowledgements are reported separately from unread status. Reads remain
lock-free, so callers needing a consistent read-modify-write operation must use
the repository's write methods. `ack` validates that the message exists for the
resolved reader and has been delivered before acknowledging it.
`record_delivery` records delivery lifecycle events and `record_relay_event`
records relay outcomes. `register_reader` sets the initial read position;
`import_messages` imports legacy message rows. `mark_concluded` persists a
concluded address, and `concluded_addresses` reads the stored set. The files
backend stores concluded addresses in `.cache/inbox/state.json`. `read_note`
resolves a `NoteRef` and returns its text.
The files adapter helpers `touch_relay_wake` and `record_send_liveness` preserve
relay wake and send telemetry side effects for non-CLI message adapters.

## Addresses

`varde_data.addresses` exposes `open_addresses(working, backend_name)` and
`varde_data.repos.addresses` exposes the `AddressRepository` protocol. Open the
repository through `open_data(...).addresses`. `varde_data.records.addresses`
exposes `AddressBinding`, `AddressEvent`, `AddressSlot`, and `ReaderContext`.

The files backend keeps address tokens under `addresses/<name>/tokens/`, the
current pointer under `addresses/<name>/current`, bindings under `bindings/`,
append-only events in `events.jsonl`, and slot records under `slots/`. Relay
state is stored in `relay/state.json`, with action records under
`relay/actions/` and the wake marker at `relay/relay.wake`. Binding
and token writes use the per-address `.lock`; event appends use
`.cache/inbox/.events.lock` after the address lock and repair a torn final line
before appending. Slot changes use `slots/.lock`. Each lock has a 30-second
timeout. Reads do not acquire these write locks.

`varde_data.service` exposes `AddressService`. Its add_alias method registers the
slot reader from the beginning before publishing the alias, preserving unread
messages already addressed to that alias.

Relay state and action files live under `.cache/inbox/relay/`; writes use
`relay/.lock` (mode `0644`, 30-second timeout) and durable atomic replacement.
A lock timeout raises `Locked`. State and action files preserve the existing
JSON format and mode `0644`. `relay_snapshot()`, `mailman_alive()`, `action()`,
and `retired()` are lock-free reads. A lock-free read can observe an action
file and `state.json` from different writes because action files are replaced
before the state file.

`address_names()` and `token_issue_times()` provide the address names (excluding
the reserved `mailman` directory) and token issue timestamps needed by prune
without exposing backend paths.
`retired_records()` returns retirement timestamps for status views.

## Work items

`varde_data.records.workitems` exposes the `WorkItem`, `Question`, and
`AuditEntry` records. `varde_data.repos.workitems` defines the backend-neutral
`WorkItemRepository` protocol. Open it with `open_workitems(root)`; `root` is
the runner data directory, and the default backend is SQLite. The in-memory
backend is available as `open_workitems(root, "memory")` for tests. Work items
are intentionally not exposed through `open_data(...).messages`.

The repository provides create, lookup, listing, planner lifecycle, question
and answer, plan decision, launch request, audit, and note operations. A create
is idempotent by key. `write_note` returns the absolute note path and
`owns_note` checks that the path belongs to the item. `workitem_store_files`
lists the SQLite database, its WAL and shared-memory files, and the notes
directory for runner watched-root setup.

SQLite opens with the shared connection configuration: WAL journaling and
`synchronous=NORMAL`. Writes use immediate transactions; state transitions and
their audit rows commit together. On first open, the backend migrates an
unversioned `workitems.sqlite3` (including the older `answer_key` and launch
request layouts) to schema version 1, adding the repository version counter.
Databases with a newer `user_version` raise `Invalid`.

`version()` returns an opaque `Version` token incremented by writes performed
through repository code. Direct edits to the database or note files do not
advance it. `questions()` orders rows by `msg_id`. Answering the final pending
question returns the item to `planning` regardless of its prior state; these
behaviors are pinned by the compatibility goldens.

Repository failures use `NotFound` and `Invalid`. The runner's
`WorkItemStore(data_dir)` facade preserves the existing API, mapping these to
`KeyError` and `ValueError`; invalid creation and question operations also map
`Invalid` to `ValueError`.

## Decisions

`varde_data.records.decisions` exposes `DecisionProjection`, `DecisionRecord`,
`AnswerEntry`, `SubmitResult`, `DeliveredReply`, and `AuditEntry`.
`varde_data.repos.decisions` exposes the `DecisionRepository` protocol and the
`IdempotencyConflict` and `AlreadyAnswered` conflict types. The repository
projects, gets, and lists decisions; dismisses and restores them; stores
idempotent answers and transitions answer entries; resolves permissions;
queries entries and delivered replies; tracks plan-writeback attempts and audit
rows; writes answer notes; and exposes `version()` and `close()`.

Open the runner's decision root with
`open_decisions(root, backend_name="sqlite", clock=...)`. The root is the
runner's data directory containing `decisions.sqlite3`, `decisions.audit.jsonl`,
and `notes/`; this domain is not registered in `open_data`. The optional clock
is a callable returning a `datetime` and supplies repository audit timestamps.
`open_sqlite_decisions(root, clock=...)` returns the typed SQLite backend for
the runner facade, which needs its connection and lock. SQLite is the production backend; `open_decisions(root, "memory")` is for
tests. `decision_store_files(root)` returns the database, its `-wal` and `-shm`
files, and the mirrored audit log for runner watched roots.

`AnswerFlow` in `varde_data.answer_flow` owns answer delivery and recovery. It
takes a repository, `send`, `read_messages`, optional `write_back` and
`recorder` callbacks, and a datetime `clock`. `submit_answer` stores an answer
before writing its note and sending it. `retry` reconciles a prior send by
matching the note path before attempting another send. `recover_sending` checks
messages for entries left in `sending`, records a matching delivery, and retries
plan writebacks. A send is claimed with an expected-state transition to
`sending`; only the caller whose transition succeeds sends the message. This
prevents concurrent retries from both sending. A sending entry without a
matching message remains `sending` for later recovery. `EntryResult` uses
`idempotency_conflict` and `already_answered` with status code 409, and rejects
answers over 20,000 characters with status code 413.

SQLite uses the shared WAL connection configuration with `synchronous=FULL`.
Writes use immediate transactions so answer state and audit changes commit
together. First open migrates an unversioned database to `user_version=1`,
adding `meta(version)`; a newer version raises `Invalid`. `version()` is an
opaque token based on the repository version counter, which advances on writes
through this repository. Writers using older code do not update that counter,
so the token cannot detect their changes. Restart the runner during deployment
to avoid a process with old code writing alongside the new version.

The runner's `DecisionStore` remains a compatibility facade. It maps a missing
permission entry (`NotFound`) to `KeyError`; answer conflicts are returned as
`EntryResult` statuses (`idempotency_conflict` or `already_answered`) rather
than propagated. `open_decisions` raises `ValueError` for an unknown backend.
`OPEN_DECISION_KINDS` and `open_decision_items` in
`varde_data.open_decisions` provide the shared pure filter for unanswered,
unacknowledged decisions from currently bound, unconcluded senders.

## Status views

`varde_data.views` exposes pure status calculations over plan records and
caller-supplied `StatusFacts`. Facts include the clock, stall threshold, now
lines, branch and merge state, task activity timestamps, and plain `Binding`
records (including `last_seen`). Their mapping inputs are copied and exposed as
immutable mappings; `StatusFacts` is hashable.

Views include task and hierarchical plan rollups, merge and awaiting-user
classification, stall details, and now-line timestamp formatting.
`plan_progress(records, children, roots)` orders roots by activity priority,
then by the dated ordering of `PurePath(record.path).parent.name`, and by
`str(record.path)` to break ties. Child dependency ties use record id then full
path. These sorts are lexical and do not access the filesystem. Public helpers include `merge_verdict`,
`parse_status_at`, `section_span`, and `section_bullets`.
`count_open_questions(body)` counts top-level bullets in the Open Questions
section and ignores fenced code. The status view performs no filesystem or
subprocess reads. It does not resolve labels, parse plan frontmatter, or render
CLI output; adapters own those operations.

The watch view is available in `varde_data.views.watch`. Its `WatchFacts` and
`ActivityFacts` records hold caller-supplied timestamps and plan facts. Pure
helpers classify plan states and transition details, calculate activity and
waiting thresholds, bind plan branches, count task states, and produce ordered
watch events. The module does not read files or invoke subprocesses.

## Friction Protocol

`varde_data.repos.friction.FrictionRepository` defines the backend-neutral
protocol for listing and showing items, recording items, status changes,
adoptions and historical captures, importing entries/events, and reading a
version token. It returns frozen request/result records and pages; analyzed
ledger records and digests use the separate ledger repository below. Event and
folded-state records (`Event`, `FrictionEventLog`, `LogState`, `LogItem`,
`LogOccurrence`, `LogStatusChange`, and `LogAdoption`) are in
`varde_data.records.friction`. The protocol exposes no SQL types or storage
paths. Open it with `open_friction(root, backend_name="files")` from
`varde_data.friction`; `"memory"` is available for tests.

The files backend stores the append-only `friction.jsonl` event stream in the
store root. This is canonical and portable; `learn.db` is a derived SQLite
index/cache that can be rebuilt from the stream. It retains the legacy schema
and ID/slug mapping needed for compatibility. The store root comes from
`VARDE_LEARN_STORE`, then `default.learn` in the Varde `config.toml`, then
`<config dir>/learn`. `resolve_learn_store` in `varde_data.paths` implements
this resolution, and `open_data(...).friction` opens the registered domain at
that root. The `friction` lock remains the event log path itself. Appends and
checked imports hold that lock; cache refresh uses SQLite's immediate write
transaction. Reads of the event stream are lock-free; reads served from the derived cache first refresh it, which takes the log lock and a write transaction, and the query then runs outside the lock.

On open/operation, an eligible populated legacy database is migrated to the
event stream under its existing migration path. The legacy DB is backed up
before migration, events are appended without replacing existing log entries,
and the database is rebuilt as the derived cache. Writes redact strings before
persisting events and store the redaction count on the event. The event stream
is append-only; cache rebuilds do not rewrite it.

`event_log()` returns a frozen `FrictionEventLog` with valid events in log
order, their original JSONL lines (including line endings), an unterminated tail
fragment, the folded state, and occurrences grouped by item event ID. The tail
is not included in `events` or `lines`; an absent or empty log returns empty
collections and an empty tail. The record exposes no storage path.

`import_events(events, dry_run=True)` compares supplied event IDs and payloads
with the current log without appending. It reports the number of identical
events already present and always reports `imported=0`. A normal import appends
only absent IDs; a present ID with a different payload raises `Conflict`.

`import_entries(entries, dry_run=True)` reports the input count in
`would_import` without checking existing slugs or conflicts. It never writes
and reports `imported=skipped=0`. A normal import deduplicates by each entry's
stored slug, preserves available legacy numeric IDs in `id_map`, and rejects
conflicting historical incident keys. Exact dry-run counts require source-side
comparison. Both dry-run modes avoid writes; event dry-run performs the
existing-log comparison, while entry dry-run is only an input-count estimate.

## Session ledger and sweep configuration

`varde_data.repos.ledger.LedgerRepository` covers the append-only
`analyzed.jsonl` session ledger and the `digests/<date>.json` files in a learn
store: `mark` appends one complete row, `analyzed` returns the latest
`LedgerRow` per harness and session pair, `seen` returns session IDs for a
harness, and `write_digest` and `read_digest` store and read a `Digest`. Reads
skip malformed rows and unreadable digests. Open it with
`open_ledger(root, backend_name="files")` from `varde_data.ledger`; `"memory"`
is available for tests.

`varde_data.sweep_config` is a validated `sweep.toml` parser that learn does not
call; learn reads `~/.config/varde/learn/sweep.toml` itself. It reads from a
config directory:
`load_sweep_repos(config_dir)` returns the configured repo paths or `None`, and
`load_summary_config(config_dir)` returns `(enabled, token_cap)`.

## Relay service

`varde_data.relay.RelayService` coordinates the address and message repositories.
`once(token_id, now=...)` escalates due messages, builds a pure relay plan from
repository snapshots, leases actions, and returns the stable `varde-relay/1`
response. `wait(token_id, timeout, ...)` polls with injectable wall clock,
monotonic clock, and sleep hook. Its optional `stop` callable is checked before
leasing and raises `Stopped` when cancellation is requested. `confirm`, `renew`,
and `end` perform the cross-repository relay workflows; repositories retain
storage operations only.

The pure planner is in `varde_data.views.relay_plan`; stale binding annotation
is in `varde_data.views.bindings`. Relay planning receives messages, bindings,
delivery events, relay events, leases, attempts, and concluded addresses as
plain snapshots, with the slot resolver passed separately as an optional
`resolve_reader` argument. It performs no filesystem or repository I/O.

The files message adapter keeps `record_send_liveness` and relay wake updates in
the same repository write path. Do not add duplicate relay-service writes for
these side effects; the `2026-10-24-data-messages-relay-dedupe` plan tracks that
deduplication. Wait writes the workflow's `gap_s` sleep key; existing planner
and liveness readers still consume `gap_seconds`.
