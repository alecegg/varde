# Dataset import format

`calibrate import DATASET --pairs PAIR_ROOT` reads one or more opaque pair
directories. `PAIR_ROOT` may be a directory containing pair directories or a
single pair directory with its own `manifest.toml`. Each pair directory
contains the two code items, one behaviour test, and a TOML manifest:

```text
PAIR_ROOT/
  <pair_id>/
    a.py
    b.py
    behaviour_test.py
    manifest.toml
```

The file extensions follow the language. Treat `<pair_id>` as an opaque id;
the exporter derives it from the pair contents and extensions, and consumers
must not infer a task, language, or side from the id.

The manifest follows the format produced by
`code/bench/quality-corpus/tools/export_pairs.py`:

```toml
id = "<pair_id>"
pair_group_id = "<task-or-refactor-group>"
language = "python"
task = "Sort the supplied values"
left = "a.py"
right = "b.py"
behaviour_test = "behaviour_test.py"
license = "MIT"

[sha256]
a = "<sha256-of-a.py-bytes>"
b = "<sha256-of-b.py-bytes>"
behaviour_test = "<sha256-of-behaviour_test.py-bytes>"
```

`id`, `pair_group_id`, `language`, `task`, `license`, all three file names,
and all three SHA-256 values are required for import. The exporter omits
`license` when the source has none; such an export is rejected by import with a
message to add a license, for example `license = "MIT"`, to `manifest.toml`.
Paths must be file names inside the pair directory. The importer checks each
digest against the file bytes before decoding the two code items as UTF-8. It
assigns the requested split to the imported items and unit (`--split` defaults
to `dev`).

The pair becomes one `pair` unit. Its two item ids are `<pair_id>:a` and
`<pair_id>:b`; both items and the unit carry `pair_group_id`. The task record
uses `pair_group_id` as its id and the manifest's `task` as its description.
The behaviour-test file's digest is checked during import and its bytes are
copied to `tasks/behaviour-tests/` under an opaque filename. The task record
stores each copied test's relative path and SHA-256. Tests are not judged items.

The current append-label API accepts pair units only. Triple and single units
can be imported and exported, but do not yet have label record formats.

The store's own JSONL and TOML files use schema version 1. The incoming pair
manifest is the exporter's interchange format and does not add a store schema
version field.

This store task owns dataset, item, unit, task, and label-batch file I/O.
Rater and session file I/O belongs to the blind-labeller task; validation
record I/O belongs to the reports task. The data shapes alone do not create
those files.
