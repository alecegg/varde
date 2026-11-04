---
type: task
status: done
depends_on: []
owns: [python/varde-workflow/src/varde_workflow/output.py, python/varde-workflow/src/varde_workflow/errors.py, python/varde-workflow/src/varde_workflow/commands/__init__.py, python/varde-workflow/src/varde_workflow/commands/common.py, python/varde-workflow/src/varde_workflow/commands/error.py, python/varde-workflow/src/varde_workflow/commands/input.py, python/varde-workflow/tests/test_base.py, python/varde-workflow/pyproject.toml]
---

Add `varde-md-core` to the package dependencies in pyproject.toml. Keep `commands/__init__.py` empty (cli-and-help owns routing). Re-export `varde_md_core.cmdbase` (output, errors, common, input; ported by python-port-md-core `command-base`) from these modules and port any workflow-only additions (state what md-core `cmdbase` already covers and what `commands/error.rs` adds). Everything else imports these; publish signatures in Progress when green.

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_base.py -q` → exit 0

#### Progress

- `varde_workflow.output` re-exports `Fix`, `for_code`, `page_bounds`, `pagination_meta`, `print_cli_failure_with_meta`, `print_cli_success`, `print_cli_success_with_meta`, `print_error`, `print_error_with_fix`, `print_failure`, `print_failure_with_fix`, `print_failure_with_meta`, `print_success`, `print_success_with_meta` from md-core.
- `varde_workflow.commands.common.resolve_bundle(bundle: Path | str | None = None) -> Path`; `varde_workflow.commands.input.read_input(file: Path | str | None = None) -> bytes`.
- md-core `cmdbase` covers `Fix`, output envelopes, pagination, `CliError`, `InternalError`, `ExitCode`, `finish`, `report_error`, `report_cli_error`, `resolve_bundle`, and `read_input`. Workflow `commands/error.rs` adds fix-aware `report_error_with_fix` and `report_failure_with_fix`; Python ports both as returning the requested exit status after rendering.
- `uv.lock` updated because the workflow package now directly depends on shared `varde-md-core` workspace package.
- Check: `uv run pytest python/varde-workflow/tests/test_base.py -q` -> 3 passed.

