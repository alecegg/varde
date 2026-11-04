# Bundle queue

Fields match the orchestrator slot table (Task, Owns, Depends, Scope) plus findings, serialization and state. Priority order A, B, C, D, E, F. All state=queued.

| id | plan dir | findings | owned files | depends_on / serialize-with | priority | state | planned_at | plan_reviewed_at | build_started_at | build_done_at | merged_at |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 2026-10-26-ux-fix-a-settings-safety | UX-001, UX-002, UX-003 | `runner/src/varde_runner/{plugins/registry.py,web/runner_config_route.py}`, `runner/tests/test_runner_config_route.py`, `runner/ui/src/routes/settings/{PolicyCard.svelte,policyEdit.*,RolesCard.svelte,roleEdit.test.js,runnerItems.test.js,+page.svelte}`, `runner/ui/src/routes/roles/{roles.ts,roles.test.js,+page.svelte}`, `runner/ui/src/lib/runnerConfigApi.ts` | none; hotfix: `registry-choices` first | 1 | merged | 2026-10-26T19:48Z|2026-10-26T20:45Z|2026-10-26T20:46Z| 2026-10-26T21:10Z | 2026-10-26T21:40Z |
| B | 2026-10-26-ux-fix-b-settings-polish | UX-009, UX-010 | `runner/ui/src/routes/settings/{SettingsNav.svelte,settingsNav.*,savedMessage.*,sdkRoles.*,SdkFlipCard.svelte,sdkFlip.test.js,RawToml.svelte,hosts.test.js,TypesCard.svelte,types.*,+page.svelte}`, `runner/src/varde_runner/web/runner_config_toml_view.py`, `runner/tests/test_runner_config_toml_view.py` | serialize-with A on settings `+page.svelte` (A `integer-runner-setting` first) | 2 | queued | 2026-10-26T19:48Z|||||
| C | 2026-10-26-ux-fix-c-approvals-launch | UX-004, UX-008 | `runner/ui/src/lib/{NeedsYou.svelte,approvalCard.*,agentsOrder.*,launchForm.*,LaunchSheet.svelte}`, `runner/ui/src/routes/settings/{firstRun.*,+page.svelte}`, `runner/ui/src/routes/agents/+page.svelte`, `runner/src/varde_runner/web/agents_route.py`, `runner/tests/{test_agents_api.py,test_launch_sheet_browser.py}`, `runner/ui/src/lib/agentsApi.ts` | serialize-with A, B on settings `+page.svelte` (`first-run-anchors` last; B adds the `harnesses` and `runner` id wrappers, C adds `status`); before E, F on agents `+page.svelte` (`approval-order-stable` first) | 3 | queued | 2026-10-26T19:48Z|||||
| D | 2026-10-26-ux-fix-d-agent-config-link | UX-007 | `runner/ui/src/lib/{AgentCard.svelte,agentConfig.*,Roster.svelte,rosterLabel.*}`, `runner/ui/src/routes/agents/profile/[id]/+page.svelte` | none | 4 | queued | 2026-10-26T19:48Z|||||
| E | 2026-10-26-ux-fix-e-agent-pins | UX-005 | `runner/ui/src/lib/{agentRow.*,agentPins.*,dragReorder.*,DragHandle.svelte,PinControls.svelte,rosterCounts.*,AgentCard.svelte,Roster.svelte}`, `runner/ui/src/routes/agents/+page.svelte` | plan depends_on D; serialize-with C on agents `+page.svelte` | 5 | queued | 2026-10-26T19:48Z|2026-10-26T20:45Z||||
| F | 2026-10-26-ux-fix-f-agent-filter | UX-006 | `runner/ui/src/lib/{agentFilter.*,agentStatus.*,AgentFilterBar.svelte,AgentCard.svelte}`, `runner/ui/src/routes/agents/+page.svelte` | plan depends_on E | 6 | queued | 2026-10-26T19:48Z|2026-10-26T20:45Z||||

Shared by every bundle: `runner/ui/package.json` (one `test:ux-<letter>` script line per bundle; the first task of each bundle creates its line; merge conflicts there are trivial and resolved by the orchestrator).

Phone-run prerequisites: all six bundles (E and F included).

## Metrics (started 2026-10-26, times UTC unless noted)
Cycle time per bundle = merged_at - planned_at; fill the timestamp columns as each state changes. Idle-gap log (observed lane idle time while work was ready):
- 2026-10-26 ~17:07-17:16Z orchestrator idle, 9 min, waiting on a wake-up (reviews had landed).
- 2026-10-26 ~17:46-17:56Z orchestrator idle ~10 min between wake-ups; relay-fix and wave 2 results sat unread.
- 2026-10-26 ~18:06-18:16Z orchestrator idle ~10 min; ux builder fix landed unrouted.
- Planners lost ~20 min to auto-mode permission prompts (luna planners, 15:30-15:55Z).
- Sonnet reviewer 013a63be refused its brief as 'main agent' (~10 min lost, 19:30-19:40Z).
