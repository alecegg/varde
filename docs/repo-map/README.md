---
kind: repo-map
commit: ddab0c7860fac0111aa640aad0f407315a991890
generated_at: 2026-11-04T12:50:40Z
scope: .
generator: varde 0.1.0
---

# Repo map

## entrypoints
- +layout ( /)  runner/ui/src/routes/+layout.svelte [page_layout]
- +page ( /)  runner/ui/src/routes/+page.svelte [page_component]
- +page ( /_catalog)  runner/ui/src/routes/_catalog/+page.svelte [page_component]
- +page ( /chat)  runner/ui/src/routes/chat/+page.svelte [page_component]
- +page ( /chat/needs)  runner/ui/src/routes/chat/needs/+page.svelte [page_component]
- +page ( /jobs)  runner/ui/src/routes/jobs/+page.svelte [page_component]
- +page ( /plans)  runner/ui/src/routes/plans/+page.svelte [page_component]
- +page ( /plans/[id])  runner/ui/src/routes/plans/[id]/+page.svelte [page_component]
- +page ( /profile/[agentId])  runner/ui/src/routes/profile/[agentId]/+page.svelte [page_component]
- +page ( /settings)  runner/ui/src/routes/settings/+page.svelte [page_component]
- +page ( /settings/[section])  runner/ui/src/routes/settings/[section]/+page.svelte [page_component]
- +page ( /thread/[agentId])  runner/ui/src/routes/thread/[agentId]/+page.svelte [page_component]
- +page ( /threads/[id])  runner/ui/src/routes/threads/[id]/+page.svelte [page_component]

## foundational_files
- data/src/varde_data/errors.py  (174 dependents, 571 refs)
- code/src/varde_code/model.py  (124 dependents, 316 refs)
- runner/src/varde_runner/config.py  (89 dependents, 633 refs)
- data/src/varde_data/config.py  (86 dependents, 345 refs)
- runner/src/varde_runner/plugins/__init__.py  (83 dependents, 415 refs)
- data/src/varde_data/open.py  (80 dependents, 289 refs)
- code/src/varde_code/parse.py  (74 dependents, 340 refs)
- code/src/varde_code/quality_score/calibration/__init__.py  (60 dependents, 63 refs)
- runner/src/varde_runner/supervisor.py  (58 dependents, 808 refs)
- data/src/varde_data/records/messages.py  (57 dependents, 331 refs)
- data/src/varde_data/records/queue.py  (53 dependents, 205 refs)
- code/src/varde_code/quality_pass/facts/__init__.py  (52 dependents, 355 refs)
- learn/src/varde_learn/loop/__init__.py  (48 dependents, 55 refs)
- learn/src/varde_learn/memory/__init__.py  (46 dependents, 59 refs)
- data/src/varde_data/queue_paths.py  (43 dependents, 66 refs)
- workflow/src/varde_workflow/inbox.py  (42 dependents, 401 refs)
- workflow/src/varde_workflow/__init__.py  (42 dependents, 51 refs)
- workflow/src/varde_workflow/commands/__init__.py  (41 dependents, 62 refs)
- data/src/varde_data/locking.py  (40 dependents, 177 refs)
- code/src/varde_code/index/build.py  (40 dependents, 156 refs)
- learn/src/varde_learn/knowledge/frontmatter.py  (40 dependents, 40 refs)
- learn/src/varde_learn/docs/pages/render.py  (38 dependents, 254 refs)
- learn/src/varde_learn/knowledge/memory.py  (37 dependents, 311 refs)
- core/src/varde_core/envelope.py  (37 dependents, 149 refs)
- data/src/varde_data/version.py  (37 dependents, 104 refs)
- learn/src/varde_learn/docs/pages/blocks_render/common.py  (36 dependents, 497 refs)
- code/src/varde_code/rules/model.py  (36 dependents, 126 refs)
- learn/src/varde_learn/docs/pages/blocks/spec.py  (36 dependents, 80 refs)
- learn/src/varde_learn/memory/entry.py  (35 dependents, 139 refs)
- code/src/varde_code/extract/provider.py  (35 dependents, 113 refs)
- data/src/varde_data/learn_store_mode.py  (34 dependents, 194 refs)
- data/src/varde_data/queue_store.py  (34 dependents, 89 refs)
- learn/src/varde_learn/docs/pages/blocks/rules.py  (33 dependents, 507 refs)
- runner/src/varde_runner/web/app.py  (33 dependents, 406 refs)
- data/src/varde_data/queue_mode_lock.py  (33 dependents, 142 refs)
- runner/src/varde_runner/__init__.py  (33 dependents, 91 refs)
- data/src/varde_data/records/addresses.py  (32 dependents, 135 refs)
- learn/src/varde_learn/docs/pages/serve.py  (31 dependents, 191 refs)
- learn/src/varde_learn/loop/improve/__init__.py  (31 dependents, 45 refs)
- learn/src/varde_learn/docs/pages/blocks_render/registry.py  (30 dependents, 54 refs)
- learn/src/varde_learn/docs/pages/blocks/__init__.py  (30 dependents, 34 refs)
- learn/src/varde_learn/docs/pages/comments.py  (29 dependents, 241 refs)
- learn/src/varde_learn/loop/errors.py  (29 dependents, 111 refs)
- code/src/varde_code/index/paths.py  (29 dependents, 72 refs)
- code/src/varde_code/__init__.py  (29 dependents, 35 refs)
- runner/src/varde_runner/plugins/registry.py  (28 dependents, 183 refs)
- workflow/src/varde_workflow/binding.py  (27 dependents, 494 refs)
- code/src/varde_code/query/params.py  (27 dependents, 159 refs)

## module_layers
- app/src/varde → app/src/varde/glue (5 files)

## subsystems
- varde_data/__init__ (data/src/varde_data/__init__.py, data/src/varde_data/backends/memory/queue.py, data/src/varde_data/backends/sqlite/queue.py, data/src/varde_data/backends/sqlite/queue_backup.py, data/src/varde_data/backends/sqlite/queue_claims.py, data/src/varde_data/backends/sqlite/queue_schema.py, data/src/varde_data/backends/sqlite/slot_claims.py, data/src/varde_data/backends/sqlite/slot_reclaim.py)
- blocks/annotated_code (learn/src/varde_learn/docs/pages/blocks/annotated_code.py, learn/src/varde_learn/docs/pages/blocks/backend.py, learn/src/varde_learn/docs/pages/blocks/callout.py, learn/src/varde_learn/docs/pages/blocks/change.py, learn/src/varde_learn/docs/pages/blocks/chart_notes.py, learn/src/varde_learn/docs/pages/blocks/charts.py, learn/src/varde_learn/docs/pages/blocks/check.py, learn/src/varde_learn/docs/pages/blocks/checklist.py)
- blocks_render/__init__ (learn/src/varde_learn/docs/pages/blocks/__init__.py, learn/src/varde_learn/docs/pages/blocks_render/adapters.py, learn/src/varde_learn/docs/pages/blocks_render/backend.py, learn/src/varde_learn/docs/pages/blocks_render/change.py, learn/src/varde_learn/docs/pages/blocks_render/code.py, learn/src/varde_learn/docs/pages/blocks_render/common.py, learn/src/varde_learn/docs/pages/blocks_render/containers.py, learn/src/varde_learn/docs/pages/blocks_render/decision.py)
- commands/handoff_checkpoint (app/src/varde/glue/handoff_checkpoint.py, app/src/varde/glue/session_notes.py, data/src/varde_data/views/__init__.py, learn/src/varde_learn/knowledge/cli.py, learn/src/varde_learn/knowledge/frontmatter.py, learn/src/varde_learn/knowledge/memory.py, learn/src/varde_learn/memory/migrate.py, learn/src/varde_learn/memory/store.py)
- langs (code/src/varde_code/extract/langs/base.py, code/src/varde_code/extract/langs/bash.py, code/src/varde_code/extract/langs/c.py, code/src/varde_code/extract/langs/cpp.py, code/src/varde_code/extract/langs/csharp.py, code/src/varde_code/extract/langs/dart.py, code/src/varde_code/extract/langs/elixir.py, code/src/varde_code/extract/langs/go.py)
- varde_runner/agent_cli (runner/src/varde_runner/agent_cli.py, runner/src/varde_runner/agent_launch.py, runner/src/varde_runner/clients.py, runner/src/varde_runner/decision_metrics.py, runner/src/varde_runner/diagnostic.py, runner/src/varde_runner/events.py, runner/src/varde_runner/instance_cap.py, runner/src/varde_runner/ipc.py)
- query/cli_scan (code/src/varde_code/cli_scan.py, code/src/varde_code/query/find_pattern.py, code/src/varde_code/query/graph.py, code/src/varde_code/query/mapping.py, code/src/varde_code/query/modes.py, code/src/varde_code/query/params.py, code/src/varde_code/query/simple.py, code/src/varde_code/query/slice_state.py)
- sba591f1b (code/src/varde_code/quality_score/samples/sba591f1b/judge-classes.cs)
- scbce10dc (code/src/varde_code/quality_score/samples/scbce10dc/judge-classes.java)
- loop/envelope (core/src/varde_core/envelope.py, learn/src/varde_learn/loop/cli_memory_knowledge.py, learn/src/varde_learn/loop/cli_memory_migrate.py, learn/src/varde_learn/loop/cli_skills_accept.py, learn/src/varde_learn/loop/cli_skills_baseline.py, learn/src/varde_learn/loop/cli_skills_candidates.py, learn/src/varde_learn/loop/cli_skills_extract.py, learn/src/varde_learn/loop/cli_skills_fill.py)
- static (learn/src/varde_learn/docs/pages/static/annotated.js, learn/src/varde_learn/docs/pages/static/chart.js, learn/src/varde_learn/docs/pages/static/code.js, learn/src/varde_learn/docs/pages/static/containers.js, learn/src/varde_learn/docs/pages/static/diagram.js, learn/src/varde_learn/docs/pages/static/dom.js, learn/src/varde_learn/docs/pages/static/flow.js, learn/src/varde_learn/docs/pages/static/image.js)
- files/__init__ (data/src/varde_data/backends/__init__.py, data/src/varde_data/backends/files/messages.py, data/src/varde_data/backends/files/messages_status.py, data/src/varde_data/backends/files/store_guard.py, data/src/varde_data/backends/memory/__init__.py, data/src/varde_data/locking.py, data/src/varde_data/records/messages.py, data/src/varde_data/relay.py)
- commands/jsonio (core/src/varde_core/jsonio.py, learn/src/varde_learn/knowledge/cmdbase/__init__.py, learn/src/varde_learn/knowledge/cmdbase/errors.py, learn/src/varde_learn/knowledge/cmdbase/output.py, workflow/src/varde_workflow/commands/check_task_ownership.py, workflow/src/varde_workflow/commands/conclude.py, workflow/src/varde_workflow/commands/execution_wave.py, workflow/src/varde_workflow/commands/handoff_check.py)
- api (serve/src/varde_serve/api/__init__.py, serve/src/varde_serve/api/docs.py, serve/src/varde_serve/api/errors.py, serve/src/varde_serve/api/read.py, serve/src/varde_serve/api/routes.py, serve/src/varde_serve/api/static.py, serve/src/varde_serve/api/write.py, serve/src/varde_serve/daemon/wiring.py)
- core/__init__ (code/src/varde_code/extract/adapter.py, code/src/varde_code/parse.py)
- glue (app/src/varde/glue/hook.py, app/src/varde/glue/hook_record.py, app/src/varde/glue/inbox_hook.py, app/src/varde/glue/memory_hook.py, app/src/varde/glue/memory_subagent.py, runner/scripts/mailbox_live_verify.py, workflow/src/varde_workflow/binding.py, workflow/src/varde_workflow/commands/address.py)
- scripts/slots_reader (data/src/varde_data/backends/files/slots_reader.py, data/src/varde_data/backends/files/strays.py, data/src/varde_data/messages.py, data/src/varde_data/service.py, data/src/varde_data/store_mode.py, runner/scripts/live_role_inbox_helpers.py, runner/scripts/live_role_inbox_verify.py, runner/scripts/mail_flip_verify.py)
- varde_data/friction_migrate (data/src/varde_data/backends/sqlite/friction_migrate.py, data/src/varde_data/backends/sqlite/friction_schema.py, data/src/varde_data/backends/sqlite/learn_friction.py, data/src/varde_data/friction_events.py, data/src/varde_data/friction_ops.py, data/src/varde_data/learn_handlers/friction.py, data/src/varde_data/records/friction.py, data/src/varde_data/testing.py)
- dependency_facts/__init__ (code/src/varde_code/rules/dependency_facts/__init__.py, code/src/varde_code/rules/dependency_facts/c_cpp.py, code/src/varde_code/rules/dependency_facts/csharp_swift.py, code/src/varde_code/rules/dependency_facts/jvm.py, code/src/varde_code/rules/dependency_facts/lua_bash.py, code/src/varde_code/rules/dependency_facts/prepare.py, code/src/varde_code/rules/dependency_facts/python.py, code/src/varde_code/rules/dependency_facts/rust.py)
- loop/calls (learn/src/varde_learn/loop/calls.py, learn/src/varde_learn/loop/calls_retention.py, learn/src/varde_learn/loop/cli_calls.py, learn/src/varde_learn/loop/cli_friction.py, learn/src/varde_learn/loop/cli_guardrails.py, learn/src/varde_learn/loop/cli_how_report.py, learn/src/varde_learn/loop/cli_skills.py, learn/src/varde_learn/loop/cli_tools.py)
- packs/cli_packs (code/src/varde_code/cli_packs.py, code/src/varde_code/errors.py, code/src/varde_code/index/paths.py, code/src/varde_code/packs/__init__.py, code/src/varde_code/packs/gitinfo.py, code/src/varde_code/packs/index_refresh.py, code/src/varde_code/packs/module_pack.py, code/src/varde_code/packs/refresh.py)
- varde_data/ledger (data/src/varde_data/backends/files/ledger.py, data/src/varde_data/backends/sqlite/learn_ledger.py, data/src/varde_data/learn_handlers/ledger.py, data/src/varde_data/learn_registry.py, data/src/varde_data/learn_store_ignore.py, data/src/varde_data/learn_store_mode.py, data/src/varde_data/ledger.py, data/src/varde_data/records/ledger.py)
- varde_toz/capture (toz/src/varde_toz/capture.py, toz/src/varde_toz/chunk.py, toz/src/varde_toz/commands/capture.py, toz/src/varde_toz/commands/migrate_metadata.py, toz/src/varde_toz/fetch.py, toz/src/varde_toz/metadata.py, toz/src/varde_toz/redact_toz.py, toz/src/varde_toz/strategies.py)
- ast_edit (app/src/varde/glue/edit.py, code/src/varde_code/__init__.py, code/src/varde_code/ast_edit/__init__.py, code/src/varde_code/ast_edit/apply.py, code/src/varde_code/ast_edit/cli.py, code/src/varde_code/ast_edit/preview.py, code/src/varde_code/cli_edit.py, code/src/varde_code/output.py)
- daemon/__init__ #3388 (serve/src/varde_serve/daemon/__init__.py, serve/src/varde_serve/daemon/lifecycle.py, serve/src/varde_serve/daemon/local_http.py, serve/src/varde_serve/daemon/state.py, serve/src/varde_serve/daemon/tokens.py, serve/src/varde_serve/mcp/__init__.py, serve/src/varde_serve/mcp/__main__.py, serve/src/varde_serve/mcp/shim.py)
- ranking (dev/src/varde_dev/calibrate/rank/commands.py, dev/src/varde_dev/calibrate/ranking/__init__.py, dev/src/varde_dev/calibrate/ranking/adaptive.py, dev/src/varde_dev/calibrate/ranking/commands.py, dev/src/varde_dev/calibrate/ranking/core.py, dev/src/varde_dev/calibrate/ranking/plan.py, dev/src/varde_dev/calibrate/ranking/sources.py, dev/src/varde_dev/calibrate/rating/__init__.py)
- search (app/src/varde/glue/module.py, app/src/varde/glue/search/__init__.py, app/src/varde/glue/search/code.py, app/src/varde/glue/search/core.py, app/src/varde/glue/search/friction.py, app/src/varde/glue/search/knowledge.py, app/src/varde/glue/search/toz.py, app/src/varde/glue/search/types.py)
- sqlite/calls (data/src/varde_data/backends/files/calls.py, data/src/varde_data/backends/sqlite/learn_calls.py, data/src/varde_data/backends/sqlite/learn_calls_retention.py, data/src/varde_data/backends/sqlite/learn_calls_upgrade.py, data/src/varde_data/backends/sqlite/learn_schema.py, data/src/varde_data/calls_store.py, data/src/varde_data/learn_handlers/calls.py, data/src/varde_data/repos/calls.py)
- varde_design/check (design/src/varde_design/check.py, design/src/varde_design/cli.py, design/src/varde_design/cli_args.py, design/src/varde_design/output.py, design/src/varde_design/render_tier.py, design/src/varde_design/reports.py, design/src/varde_design/settings.py, design/src/varde_design/sources.py)
- varde_runner/measure (runner/scripts/check_resource_budget.py, runner/src/varde_runner/config.py, runner/src/varde_runner/config_io.py, runner/src/varde_runner/generate.py, runner/src/varde_runner/plugins/pi_durable/__init__.py, runner/src/varde_runner/web/registry.py, runner/src/varde_runner/web/roles.py)
- docs (learn/src/varde_learn/docs/__init__.py, learn/src/varde_learn/docs/baseline.py, learn/src/varde_learn/docs/baseline_cmd.py, learn/src/varde_learn/docs/cli.py, learn/src/varde_learn/docs/flow/model.py, learn/src/varde_learn/docs/flow/resolve.py, learn/src/varde_learn/docs/how_cmd.py)
- extract/recursion (code/src/varde_code/extract/recursion.py, code/src/varde_code/extract/symbol.py, code/src/varde_code/index/persist/edges.py, code/src/varde_code/model.py, code/src/varde_code/query/entrypoints.py, code/src/varde_code/query/flows.py, code/src/varde_code/rules/index_reader.py)
- files/plans (data/src/varde_data/backends/files/plans.py, data/src/varde_data/backends/files/plans_index.py, data/src/varde_data/backends/files/plans_write.py, data/src/varde_data/backends/sqlite/plans.py, data/src/varde_data/frontmatter_patch.py, data/src/varde_data/plans.py, data/src/varde_data/records/plans.py)
- loop/cli_friction_write (learn/src/varde_learn/loop/cli_friction_write.py, learn/src/varde_learn/loop/errors.py, learn/src/varde_learn/loop/importer.py, learn/src/varde_learn/loop/redact.py, learn/src/varde_learn/loop/store/__init__.py, learn/src/varde_learn/loop/store/paths.py, learn/src/varde_learn/loop/store_dir.py)
- pages/__init__ #2366 (learn/src/varde_learn/docs/pages/__init__.py, learn/src/varde_learn/docs/pages/cli.py, learn/src/varde_learn/docs/pages/comments.py, learn/src/varde_learn/docs/pages/store.py, learn/src/varde_learn/docs/pages/watch.py, serve/src/varde_serve/events/watchers.py, toz/src/varde_toz/daemon/client.py)
- reports/commands (dev/src/varde_dev/calibrate/report/commands.py, dev/src/varde_dev/calibrate/reports/commands.py, dev/src/varde_dev/calibrate/reports/config.py, dev/src/varde_dev/calibrate/reports/dataset.py, dev/src/varde_dev/calibrate/reports/validation.py, dev/src/varde_dev/calibrate/sample/__init__.py, dev/src/varde_dev/calibrate/validate/commands.py)
- varde_workflow/watch (data/src/varde_data/views/watch.py, workflow/src/varde_workflow/collector_facts.py, workflow/src/varde_workflow/collectors.py, workflow/src/varde_workflow/commands/watch.py, workflow/src/varde_workflow/commands/watch_cache.py, workflow/src/varde_workflow/merge_state.py, workflow/src/varde_workflow/watch_cache.py)
- blocks/fences (learn/src/varde_learn/docs/pages/blocks/fences.py, learn/src/varde_learn/docs/pages/blocks/lines_check.py, learn/src/varde_learn/docs/pages/blocks/statement.py, learn/src/varde_learn/docs/pages/lines/__init__.py, learn/src/varde_learn/docs/pages/lines/parse.py, learn/src/varde_learn/loop/improve/report_page.py)
- blocks_render/001-lysine_dev_okhttp-tagsseededfromrequest (learn/src/varde_learn/docs/pages/blocks_render/chart_draw.py, learn/src/varde_learn/docs/pages/blocks_render/chart_events.py, learn/src/varde_learn/docs/pages/blocks_render/chart_model.py, learn/src/varde_learn/docs/pages/blocks_render/chart_scale.py)
- commands/messages (data/src/varde_data/backends/sqlite/messages.py, data/src/varde_data/role_inbox.py, workflow/src/varde_workflow/commands/__init__.py, workflow/src/varde_workflow/commands/msg.py, workflow/src/varde_workflow/commands/msg_doctor.py, workflow/src/varde_workflow/send_liveness.py)
- index/__init__ (code/src/varde_code/index/__init__.py, code/src/varde_code/index/_refresh_fastpath.py, code/src/varde_code/index/incremental.py, code/src/varde_code/index/persist/__init__.py, code/src/varde_code/index/persist/entities.py, code/src/varde_code/index/persist/metrics.py)
- memory/__init__ (learn/src/varde_learn/memory/__init__.py, learn/src/varde_learn/memory/entry.py, learn/src/varde_learn/memory/migrate_knowledge.py, learn/src/varde_learn/memory/migrated.py, learn/src/varde_learn/memory/searchindex.py, learn/src/varde_learn/memory/share.py)
- output/codex (learn/src/varde_learn/loop/codex.py, learn/src/varde_learn/loop/output/__init__.py, learn/src/varde_learn/loop/output/calibrate.py, learn/src/varde_learn/loop/output/command.py, learn/src/varde_learn/loop/output/run.py, learn/src/varde_learn/loop/trigger.py)
- quality_score/010-lysine_dev_okhttp-run (code/src/varde_code/git.py, code/src/varde_code/quality_score/cli/__init__.py, code/src/varde_code/quality_score/file_facts.py, code/src/varde_code/quality_score/vs.py, code/src/varde_code/scan/changed_since.py)
- varde/cli (app/src/varde/cli.py, app/src/varde/discovery.py, app/src/varde/help/route_snapshots.py, app/src/varde/help/snapshots.py, app/src/varde/setup/dispatch.py, core/src/varde_core/module.py)
- varde_runner/cache (runner/src/varde_runner/cache.py, runner/src/varde_runner/open_decisions.py, runner/src/varde_runner/wake.py, runner/src/varde_runner/web/app.py, runner/src/varde_runner/web/cache.py, runner/src/varde_runner/web/pins.py)
- varde_runner/deploy (runner/deploy/deploy.py, runner/scripts/pi_durable_smoke_env.py, runner/src/varde_runner/__init__.py, runner/src/varde_runner/service/__init__.py, runner/src/varde_runner/workspace_cli.py, workflow/src/varde_workflow/commands/error.py)
- varde_runner/relay_prune (data/src/varde_data/relay_prune.py, runner/scripts/relay_e2e.py, runner/src/varde_runner/bot_wake.py, runner/src/varde_runner/relay.py, runner/src/varde_runner/relay_cli.py, runner/src/varde_runner/relay_prune.py)
- varde_toz/doctor (toz/src/varde_toz/commands/doctor.py, toz/src/varde_toz/commands/event_note.py, toz/src/varde_toz/commands/hook.py, toz/src/varde_toz/config.py, toz/src/varde_toz/hook.py, toz/src/varde_toz/hook_main.py)
- varde_workflow/config (data/src/varde_data/config.py, data/src/varde_data/open.py, runner/scripts/native_smoke.py, workflow/src/varde_workflow/mail_retirement.py, workflow/src/varde_workflow/pulse_mail.py, workflow/src/varde_workflow/retired.py)
- breakdown (code/src/varde_code/quality_score/breakdown/__init__.py, code/src/varde_code/quality_score/breakdown/fix_targets.py, code/src/varde_code/quality_score/calibration/__init__.py, code/src/varde_code/quality_score/samples/vectors.py, code/src/varde_code/quality_score/scoring/__init__.py)
- claude-sdk/index (runner/node-host/engines/claude-sdk/index.mjs, runner/node-host/engines/claude-sdk/interrupt.mjs, runner/node-host/engines/claude-sdk/options.mjs, runner/node-host/engines/claude-sdk/permission.mjs, runner/node-host/engines/claude-sdk/watchdog.mjs)

## symbols
(truncated: 0/100 shown; code_query mode=filter_symbols for the full symbol list)

## flows
(truncated: 0/1 shown; code_query mode=explore on an entrypoint symbol (direction=outgoing) for its full call tree, or raise maxTokensEstimate to list more flows)

## hotspots
(truncated: 0/50 shown; code_query mode=hotspots for the full ranked list)

## truncated (token budget)
- subsystems: 59/300 shown — raise maxTokensEstimate to list more subsystems
- flows: 0/1 shown — code_query mode=explore on an entrypoint symbol (direction=outgoing) for its full call tree, or raise maxTokensEstimate to list more flows
- symbols: 0/100 shown — code_query mode=filter_symbols for the full symbol list
- hotspots: 0/50 shown — code_query mode=hotspots for the full ranked list
- module_layers.edges: 1/426 shown — raise maxTokensEstimate; module_layers holds the resolved module-dependency graph
- module_layers.cycles: 0/21 shown — raise maxTokensEstimate; module_layers holds the resolved module-dependency graph

