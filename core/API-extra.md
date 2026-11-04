# Post-freeze API mapping

This supplement maps the interim `varde_toz._core` compatibility surface to the
integrated core. `API.md` remains frozen; use these core calls when replacing
the shim in `varde-toz`.

## Shim calls to core calls

| Shim surface | Before (shim) | After (core) | Mapping notes |
|---|---|---|---|
| `redact` | `redact(text, builtin=True, patterns=(), values=None, reveal=2)` | `Redactor(RedactConfig(builtin=True, patterns=(), values=[SecretValue(name, value), ...], reveal=2)).redact(text)` | Shim `values` is a name-to-text dict; convert its items to `SecretValue` records. The returned core `Redacted.notices` uses `Kind` enum values and a list; shim notices use string kinds and a tuple. `Redacted.text` and notice labels/counts carry over. |
| `varde_config_dir` | `varde_config_dir(env=None)` | `varde_config_dir()` | Set environment variables before calling core. The shim's explicit `env` injection has no core parameter equivalent. |
| `data_dir` | `data_dir(env=None, platform=None)` | `data_dir()` | Set environment variables and use the actual platform; the shim's explicit environment/platform injection has no core parameter equivalent. |
| `configure_connection` | `configure_connection(connection)` | `configure_connection(connection)` | Same call shape and behavior. |
| `append_entry` | `append_entry(document, event, entry)` | `from varde.json_order import append_entry` (app, no longer in core) | Same call shape and behavior. |
| `remove_matching_commands` | `remove_matching_commands(document, event, predicate)` | `from varde.json_order import remove_matching_commands` (app, no longer in core) | Same call shape. Behavior differs when the last command is removed: the shim keeps the event as an empty array, while core removes the empty event and leaves `hooks` as an empty object. The shim is wrong; toz-adopt must expect `"hooks": {}`. |
| `TOZ_BLOCK_START`, `TOZ_BLOCK_END`, `TOZ_NOTE` | `from varde_toz._core import ...` | `from varde_core.constants import ...` | Values are shared constants. |

The shim's internal `BUILTIN`, `BUILTIN_RULES`, `BUILTIN_HINTS`, and
`ENV_ASSIGNMENT_HINT` are implementation details, with no public core
equivalent. The core redactor owns its rules internally.

## Observed shim/core mismatch

`remove_matching_commands` returns the same removed-command list, but its JSON
result differs when all entries are removed. The shim's `"Start": []` result is
wrong: Rust and core remove the event and render `"hooks": {}`. The toz-adopt
case must be updated to expect the core result.

## Additional imports frozen after `API.md`

- `varde_core.redact`: `RedactConfig`, `Redactor`, `Redacted`, `Notice`,
  `Kind`, `SecretValue`, `Span`, and `values`.
- `varde_core.text_audit`: `audit`, `Finding`, `Severity`, `Rule`, and
  `expand_skill_dir`.
- `varde_core.skill_relations`: `parse`, `Relations`, `RelationError`,
  `closure`, and `IMPLICIT_SKILL`.
- `varde_learn.loop.errors`: `LearnError`, `NotImplemented`, `Usage`, `StoreConfig`,
  `StoreInvalid`, `StoreItemNotFound`, `StoreInsideGit`, `StoreSchemaTooNew`,
  `StoreSchemaVersion`, `StoreGitCheck`, `StoreIo`, `StoreDatabase`, and
  `Diagnose`.
- `varde_learn.loop.redact`: `Redacted` and `apply`.
- `varde_learn.loop.store_dir`: `resolve_store_dir`.

