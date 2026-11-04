# Manager bot

The manager bot (role `manager-bot`) chats in the `main` thread and launches and
manages agents through the runner API. Limits are enforced by the runner, at the
API gateway or the permission hook; prompts only describe them. Only the
`claude-cli` adapter can enforce the restricted profile (`bot_profile.py`); other
adapters refuse a bot launch. The bot starts in slot `manager`.

All paths below are under `runner/src/varde_runner/`.

## Pairing

`user_only` routes need the paired user browser (cookie plus CSRF header,
`web/pairing_route.py`). Read the one-time code with `varde-runner pairing-code`
and enter it on the pairing screen once. A wrong code is refused and repeated
wrong codes burn it. Credential files: `docs/sandbox-permissions.md`.

## Gateway

Every request with a bot or descendant token passes `bot_gateway.py`: route policy
(`bot_route_policy.py`), then pause state, constraints (`bot_constraints.py`),
governor (`bot_governor.py`, `bot_control.py`), a `call` audit row, the handler,
a `result` row. An unclassified or unknown route is denied; a test fails when the
app serves a route the policy table lacks.

Allowed writes (everything else is refused):

| Action | Route | Constraint |
| --- | --- | --- |
| Launch | `POST /api/agents` | role in `bot.launch_roles` (default `orchestrator`, `planner`, `explorer`); listed workspace; slot not `main` or `manager` |
| Prompt, interrupt, resume, stop, archive | `POST /api/agents/{id}/{action}` | agent launched by the caller's own branch of the bot; never `respond` or `mode` |
| Stub, queue move | `POST /api/work-items`, `POST /api/queue/move` | stub fields; existing plans |
| Plan comment, plan body | `POST /api/plans/{id}/comments`, `PUT /api/plans/{id}/body` | sender `manager`; backlog plans, body only |
| Say, notes, mailbox | `POST /api/bot/say`, `/api/bot/notes`, `/api/bot/mailbox` | own thread and notes |
| Reads | `GET` routes classified `read`, `GET /api/identities` | read-only |

## Never without the user

Refused with 403 and a `denied` audit row (`user_only` and user-data routes in
`bot_route_policy.py`): approving merges, answering, dismissing or restoring
Mailbox items, `respond`, settings, roles, guard, jobs, identity profiles,
`runner.toml` and restart, chat send as the user, instance-thread takeover,
`/api/bot/control` (pause, resume, kill), and every delete. There is no route that
edits the bot's policy, caps or audit. These stay 403 while the bot is paused;
allowlisted writes answer 423 while paused or killed.

Outside the gateway, the permission hook (`bot_permissions.py`) allows only
`varde-runner bot act <name>`, `varde plan status|readiness|merged <plan>` and
`varde msg read --as manager`, and the restricted profile and token-only child
environment keep credentials out of reach.

## Caps and pause

Caps come from `[bot]` in `runner.toml`; only the user edits the file. Defaults
are in `bot_governor.py`.

| Cap | Default | Over the cap |
| --- | --- | --- |
| `max_concurrent_agents` (descendants included) | 4 | 429 |
| `max_launches_per_hour` | 6 | 429 |
| `max_actions_per_minute` | 30 | 429 |
| `daily_token_budget` | 5,000,000 | 423 and the bot pauses (80% posts a warning) |
| `stop_agents_on_stop` | true | pause at 100% budget and Kill stop bot-launched agents |

A loop (same action 3 times in 10 minutes, two launch-stop cycles on one plan in
30 minutes, 20 refused calls in 5 minutes) pauses the bot and raises a Mailbox
item; agents keep running. State is `running`, `paused` or `killed`, persists
across restart. The governor can pause it automatically (budget, loop;
`bot_control.py`); only `user_only` routes resume or kill it (the chat header
chip, Pause or Resume button, and Kill behind a confirm). Kill needs a new
generation.

## Audit and delegation

`bot_audit.py` rows are append-only (database triggers refuse update and delete).
A failed `call` write refuses the request with 503. The Audit sheet reads
`GET /api/bot/audit`.

The bot reads `GET /api/identities` and picks by description. A match launches
that identity within caps; no match launches the closest allowed role and the
launch handler posts one line to `main`. Builders and reviewers come only through
an orchestrator.

## Residual risk

Descendants (agents the bot launched) carry a taint token (`bot_taint.py`) that
the agent CLIs forward; with it, everything above binds them. A tokenless
descendant is bound only by `user_only` routes (the paired cookie, including chat
send and takeover) and the merge gate (`varde plan merge` and the
`pre-merge-commit` check refuse without the approval record). Caps, launch roles,
own-agents-only and queue limits are cooperative for it. A direct
`git merge --no-verify` is detected afterwards by `varde plan merged`, which raises
a Mailbox item; it is not prevented. A same-user agent can read the pairing secret
unless the sandbox denies the directory.

## Go-live check

Launch the bot in production only after
`uv run pytest runner/tests/test_bot_forbidden.py runner/tests/test_bot_route_policy.py runner/tests/test_bot_browser.py -q`
passes with the UI built (`just build-ui`); browser tests skip when it is not.
Fix a failure in the owning task; do not weaken the suite.
