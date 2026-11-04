---
kind: module-pack
commit: ddab0c7860fac0111aa640aad0f407315a991890
generated_at: 2026-11-04T12:50:45Z
scope: code
generator: varde 0.1.0
---

# Module code

## entrypoints
(none)

## foundational_files
- code/src/varde_code/model.py  (124 dependents, 316 refs)
- code/src/varde_code/parse.py  (74 dependents, 340 refs)
- code/src/varde_code/quality_score/calibration/__init__.py  (60 dependents, 63 refs)
- code/src/varde_code/quality_pass/facts/__init__.py  (52 dependents, 355 refs)
- code/src/varde_code/index/build.py  (40 dependents, 156 refs)
- code/src/varde_code/rules/model.py  (36 dependents, 126 refs)
- code/src/varde_code/extract/provider.py  (35 dependents, 113 refs)
- code/src/varde_code/index/paths.py  (29 dependents, 72 refs)
- code/src/varde_code/__init__.py  (29 dependents, 35 refs)
- code/src/varde_code/query/params.py  (27 dependents, 159 refs)
- code/src/varde_code/quality_score/samples/sba591f1b/judge-names.cs  (26 dependents, 74 refs)
- code/src/varde_code/extract/langs/base.py  (25 dependents, 864 refs)
- code/src/varde_code/query/__init__.py  (25 dependents, 85 refs)
- code/src/varde_code/extract/__init__.py  (25 dependents, 25 refs)
- code/src/varde_code/quality_pass/pass_/__init__.py  (24 dependents, 25 refs)
- code/src/varde_code/extract/entity.py  (23 dependents, 81 refs)
- code/src/varde_code/quality_score/__init__.py  (23 dependents, 24 refs)
- code/src/varde_code/quality_resolve/__init__.py  (23 dependents, 23 refs)
- code/src/varde_code/rules/finding.py  (22 dependents, 89 refs)
- code/src/varde_code/extract/langs/__init__.py  (20 dependents, 40 refs)
- code/src/varde_code/quality_score/scoring/__init__.py  (20 dependents, 20 refs)
- code/src/varde_code/seams.py  (16 dependents, 25 refs)
- code/src/varde_code/quality_score/fixedpoint/__init__.py  (15 dependents, 16 refs)
- code/src/varde_code/index/incremental.py  (14 dependents, 83 refs)
- code/src/varde_code/git.py  (14 dependents, 42 refs)
- code/src/varde_code/scan/__init__.py  (14 dependents, 14 refs)
- code/src/varde_code/rules/dependency_facts/types.py  (13 dependents, 87 refs)
- code/src/varde_code/index/slice.py  (13 dependents, 72 refs)
- code/src/varde_code/quality_score/reference.py  (13 dependents, 64 refs)
- code/src/varde_code/query/modes.py  (13 dependents, 34 refs)
- code/src/varde_code/rules/__init__.py  (13 dependents, 13 refs)
- code/src/varde_code/complexity.py  (12 dependents, 105 refs)
- code/src/varde_code/quality_score/breakdown/__init__.py  (11 dependents, 34 refs)
- code/src/varde_code/index/__init__.py  (11 dependents, 12 refs)
- code/src/varde_code/query/nav_map.py  (10 dependents, 80 refs)
- code/src/varde_code/query/output.py  (10 dependents, 75 refs)

## module_layers
- app/src/varde/glue → code/src/varde_code/index (3 files)

## subsystems
- langs (code/src/varde_code/extract/langs/base.py, code/src/varde_code/extract/langs/bash.py, code/src/varde_code/extract/langs/c.py, code/src/varde_code/extract/langs/cpp.py, code/src/varde_code/extract/langs/csharp.py, code/src/varde_code/extract/langs/dart.py, code/src/varde_code/extract/langs/elixir.py, code/src/varde_code/extract/langs/go.py)
- query/cli_scan (code/src/varde_code/cli_scan.py, code/src/varde_code/query/find_pattern.py, code/src/varde_code/query/graph.py, code/src/varde_code/query/mapping.py, code/src/varde_code/query/modes.py, code/src/varde_code/query/params.py, code/src/varde_code/query/simple.py, code/src/varde_code/query/slice_state.py)
- sba591f1b (code/src/varde_code/quality_score/samples/sba591f1b/judge-classes.cs)
- scbce10dc (code/src/varde_code/quality_score/samples/scbce10dc/judge-classes.java)
- core/__init__ (code/src/varde_code/extract/adapter.py, code/src/varde_code/parse.py)
- dependency_facts/__init__ (code/src/varde_code/rules/dependency_facts/__init__.py, code/src/varde_code/rules/dependency_facts/c_cpp.py, code/src/varde_code/rules/dependency_facts/csharp_swift.py, code/src/varde_code/rules/dependency_facts/jvm.py, code/src/varde_code/rules/dependency_facts/lua_bash.py, code/src/varde_code/rules/dependency_facts/prepare.py, code/src/varde_code/rules/dependency_facts/python.py, code/src/varde_code/rules/dependency_facts/rust.py)
- packs/cli_packs (code/src/varde_code/cli_packs.py, code/src/varde_code/errors.py, code/src/varde_code/index/paths.py, code/src/varde_code/packs/__init__.py, code/src/varde_code/packs/gitinfo.py, code/src/varde_code/packs/index_refresh.py, code/src/varde_code/packs/module_pack.py, code/src/varde_code/packs/refresh.py)
- ast_edit (code/src/varde_code/__init__.py, code/src/varde_code/ast_edit/__init__.py, code/src/varde_code/ast_edit/apply.py, code/src/varde_code/ast_edit/cli.py, code/src/varde_code/ast_edit/preview.py, code/src/varde_code/cli_edit.py, code/src/varde_code/output.py)
- extract/recursion (code/src/varde_code/extract/recursion.py, code/src/varde_code/extract/symbol.py, code/src/varde_code/index/persist/edges.py, code/src/varde_code/model.py, code/src/varde_code/query/entrypoints.py, code/src/varde_code/query/flows.py, code/src/varde_code/rules/index_reader.py)
- index/__init__ (code/src/varde_code/index/__init__.py, code/src/varde_code/index/_refresh_fastpath.py, code/src/varde_code/index/incremental.py, code/src/varde_code/index/persist/__init__.py, code/src/varde_code/index/persist/entities.py, code/src/varde_code/index/persist/metrics.py)
- quality_score/010-lysine_dev_okhttp-run (code/src/varde_code/git.py, code/src/varde_code/quality_score/cli/__init__.py, code/src/varde_code/quality_score/file_facts.py, code/src/varde_code/quality_score/vs.py, code/src/varde_code/scan/changed_since.py)
- breakdown (code/src/varde_code/quality_score/breakdown/__init__.py, code/src/varde_code/quality_score/breakdown/fix_targets.py, code/src/varde_code/quality_score/calibration/__init__.py, code/src/varde_code/quality_score/samples/vectors.py, code/src/varde_code/quality_score/scoring/__init__.py)
- cli (code/src/varde_code/quality_score/baseline_tests.py, code/src/varde_code/quality_score/cli/baseline.py, code/src/varde_code/quality_score/cli/baseline_page.py, code/src/varde_code/quality_score/cli/baseline_server.py, code/src/varde_code/quality_score/cli/baseline_service.py)
- cognitive (code/src/varde_code/extract/entity.py, code/src/varde_code/extract/preproc.py, code/src/varde_code/quality_pass/cognitive/__init__.py, code/src/varde_code/quality_pass/cognitive/entities.py, code/src/varde_code/quality_pass/cognitive/logical.py)
- quality_score/reference (code/src/varde_code/quality_score/cli/reference.py, code/src/varde_code/quality_score/fix_explain.py, code/src/varde_code/quality_score/guidance.py, code/src/varde_code/quality_score/reference.py, code/src/varde_code/scan/quality_verdict.py)
- resolve (code/src/varde_code/index/resolve/aux.py, code/src/varde_code/index/resolve/calls.py, code/src/varde_code/index/resolve/core.py, code/src/varde_code/index/resolve/hierarchy.py, code/src/varde_code/index/resolve/imports.py)
- rules/clone_verification (code/src/varde_code/rules/clone_verification.py, code/src/varde_code/rules/correlate.py, code/src/varde_code/rules/finding.py, code/src/varde_code/rules/suppress.py, code/src/varde_code/scan/integrity.py)
- calibration (code/src/varde_code/quality_score/calibration/loading.py, code/src/varde_code/quality_score/calibration/overlay.py, code/src/varde_code/quality_score/fixedpoint/arithmetic.py, code/src/varde_code/quality_score/fixedpoint/scope.py)
- cpp/021-fmtlib_fmt-is_big_endian (code/src/varde_code/quality_pass/__init__.py, code/src/varde_code/quality_pass/facts/__init__.py, code/src/varde_code/quality_pass/pass_/read.py)
- csharp/019-app_vnext_polly-executecore (code/src/varde_code/extract/provider.py, code/src/varde_code/index/build.py, code/src/varde_code/quality_score/__init__.py)
- query/foundational_files (code/src/varde_code/query/foundational_files.py, code/src/varde_code/query/noise_filter.py, code/src/varde_code/query/subsystems.py, code/src/varde_code/query/symbols_section.py)
- rules/loader (code/src/varde_code/rules/loader.py, code/src/varde_code/rules/model.py, code/src/varde_code/rules/overrides.py, code/src/varde_code/rules/pattern.py)
- graph/__init__ (code/src/varde_code/quality_pass/graph/__init__.py, code/src/varde_code/quality_pass/graph/depth.py, code/src/varde_code/quality_pass/graph/tree.py)
- index/cli_index (code/src/varde_code/cli_index.py, code/src/varde_code/index/supervise.py, code/src/varde_code/index/watch.py)
- index/db (code/src/varde_code/index/db.py, code/src/varde_code/index/slice.py, code/src/varde_code/seams.py)
- packs/JavacTargets (code/src/varde_code/packs/header.py, code/src/varde_code/packs/repo_map.py)
- pass_ (code/src/varde_code/quality_pass/pass_/index_read.py, code/src/varde_code/quality_pass/pass_/keys.py, code/src/varde_code/quality_pass/pass_/run.py)
- smap (code/src/varde_code/quality_score/fixedpoint/__init__.py, code/src/varde_code/quality_score/smap/__init__.py, code/src/varde_code/quality_score/smap/mapping.py)
- core/cli (code/src/varde_code/quality_resolve/langs/typescript.py)
- costs (code/src/varde_code/quality_score/costs/__init__.py, code/src/varde_code/quality_score/costs/costs.py)
- dependency_facts/elixir_haskell (code/src/varde_code/rules/dependency_facts/elixir_haskell.py, code/src/varde_code/rules/dependency_facts/ruby_php.py)
- extract/__init__ (code/src/varde_code/extract/__init__.py, code/src/varde_code/extract/langs/__init__.py)
- graph/fragments (code/src/varde_code/quality_pass/graph/fragments.py, code/src/varde_code/quality_pass/pass_/measures.py)
- index/certified (code/src/varde_code/index/certified.py, code/src/varde_code/index/churn.py)
- index/provenance (code/src/varde_code/index/provenance.py, code/src/varde_code/query/staleness.py)
- index/prune (code/src/varde_code/index/prune.py, code/src/varde_code/index/repo_lock.py)
- pathclass (code/src/varde_code/quality_pass/pathclass/__init__.py, code/src/varde_code/quality_pass/pathclass/classes.py)
- quality_pass (code/src/varde_code/quality_pass/resolve_hook.py, code/src/varde_code/quality_resolve/__init__.py)
- quality_score/user_text (code/src/varde_code/quality_score/user_text.py, code/src/varde_code/quality_score/user_view.py)
- query/__init__ (code/src/varde_code/query/__init__.py, code/src/varde_code/query/freshness.py)
- query/module_layers (code/src/varde_code/query/module_layers.py, code/src/varde_code/query/nav_map.py)
- scan/__init__ (code/src/varde_code/scan/__init__.py, code/src/varde_code/scan/quality_scores.py)
- scan/quality_mode (code/src/varde_code/scan/quality_mode.py, code/src/varde_code/scan/quality_wiring.py)
- scan/report (code/src/varde_code/scan/report.py, code/src/varde_code/scan/report_run.py)
- store/__init__ (code/src/varde_code/quality_pass/store/__init__.py, code/src/varde_code/quality_pass/store/store.py)
- tuner (code/src/varde_code/quality_score/tuner/__init__.py, code/src/varde_code/quality_score/tuner/tuning.py)
- varde_code/cli_query (code/src/varde_code/cli_query.py, code/src/varde_code/query/output.py)
- varde_code/graph_model (code/src/varde_code/graph_model.py, code/src/varde_code/index/persist/graph.py)
- varde_core/loading (code/src/varde_code/quality_score/samples/loading.py)

## symbols
- code/src/varde_code/quality_pass/facts/__init__.py::extract_facts  (49 callers)
- code/src/varde_code/index/build.py::build  (38 callers)
- code/src/varde_code/extract/provider.py::CodeExtractionProvider  (34 callers)
- code/src/varde_code/parse.py::parse_source  (34 callers)
- code/src/varde_code/parse.py::language_for_path  (31 callers)
- code/src/varde_code/model.py::Span  (29 callers)
- code/src/varde_code/quality_score/samples/sba591f1b/judge-names.cs::ToLowerInvariant  (26 callers)
- code/src/varde_code/extract/langs/base.py::LanguageTables  (23 callers)
- code/src/varde_code/index/paths.py::repo_db_path  (22 callers)

## flows
(none)

## hotspots
(truncated: 0/50 shown; code_query mode=hotspots for the full ranked list)

## truncated (token budget)
- symbols: 11/100 shown — code_query mode=filter_symbols for the full symbol list
- hotspots: 0/50 shown — code_query mode=hotspots for the full ranked list
- module_layers.edges: 1/162 shown — raise maxTokensEstimate; module_layers holds the resolved module-dependency graph
- module_layers.cycles: 0/8 shown — raise maxTokensEstimate; module_layers holds the resolved module-dependency graph

