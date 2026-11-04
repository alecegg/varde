# Runner identities

The `/agents` roster groups live runner sessions by role. Role names and
profiles are separate: profiles supply the display name, short label, and
description shown for each identity.

## Profile files

Profiles live in `<config dir>/identities/<id>.toml`. The config directory is
selected by `VARDE_RUNNER_CONFIG_DIR`, or defaults to `~/.config/varde`.
The filename stem is the identity id. Supported ids are the runner roles and
`manager`.

Each file has four string fields:

```toml
name = "Builder"
label = "builder"
description = "Implements assigned changes."
role = "builder"
```

`name` must contain 1 to 40 characters, `label` 1 to 24 characters, and
`description` at most 280 characters. `role` is read-only and must match the
file's id. Missing files use built-in defaults and are not created until saved.
An invalid profile falls back to defaults and reports an error in the roster.

## Profile screen

Choose **Edit profile** on an identity in the `/agents` roster to change its
name, label, and description. The role is displayed but cannot be changed.
Saving writes only that identity's profile file; validation errors stay beside
the affected field. An invalid hand-edited file opens with the default values
and its parse error, and saving replaces that file with a valid profile.

Role descriptions have one source: `identity_profile.py` supplies the defaults
through `GET /api/identities`. The Roles page reads those same descriptions, so
an edited profile description appears consistently in both places.

## Roster API

- `GET /api/identities` returns profiles with live instance counts and their
  worst state. Only Orchestrators include instances in this response.
- `GET /api/identities/{id}/instances?include=all` returns all instances for
  an identity.
- `PUT /api/identities/{id}` saves `{name, label, description}`. The role is
  fixed by the id. Invalid fields return `400`; unknown ids return `404`.

Live instances are sessions not completed or archived. The roster shows a
count for worker roles and expands Orchestrators by plan or workspace.
Roster counts and states cover live agents only, excluding completed and
archived sessions. The agent list below the roster is history: it still lists
completed agents, while archived agents remain behind the existing toggle.

## Instance limit

The runner allows at most eight live instances by default. Set
`max_live_instances` in the `[limits]` table in `runner.toml` to change the
limit; it must be an integer of at least one. The same limit applies to
sessions started by users, orchestrators, and the runner bot.
