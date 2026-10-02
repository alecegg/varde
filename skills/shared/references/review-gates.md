# Independent review gates

Gate every implementation change (source, configuration, documentation,
fixes, refactors, prototypes in source) through `varde-change`. Read-only
investigation, workflow bookkeeping, and prototype files under `<working>`
need no gate.

Coordinators read this file; an executor with a caller-supplied subject runs
only the checkpoints its brief names, and a gate reviewer follows
`references/review-gate-record.md` instead.

## 1. Mechanical edit exception

An edit qualifies only if its entire diff preserves exact operational meaning
and only corrects:

- spelling
- punctuation
- whitespace
- formatting

Take the full gate for mixed or uncertain diffs and for changes to any of:

- commands
- paths
- conditions
- instruction meaning
- output contracts
- configuration
- code
- tests

When using the exception:

- Inspect the final diff and run targeted checks.
- Report why it qualified and what passed.
- Skill edits still get `varde-agent-doc-authoring` review, limited to its
  length check and a diff inspection.
- Existing review subjects keep all checkpoints.
- Work that grows beyond the exception takes the full gate first.

## 2. Initialize the subject

Pick the branch first:

- Persisted plan, or a contract/scope mutation: load
  `references/review-gate-plan.md` before initialization or mutation, and
  initialize there.
- Different execution checkout: load `references/review-gate-worktree.md`
  before dispatch or editing there; a subject binds its exact approval
  checkout.

For bounded work:

1. Store a JSON contract under `subjects/<safe-id>/` in the configured
   working store, not inside the CLI-owned `review-gates/` directory, with
   these keys:
   - `outcome`
   - `scope`
   - `assumptions`
   - `design`
   - `open_choices`
   - `verification`
2. Compute the risk tier: run
   `python3 <skill-dir>/scripts/risk-tier.py <scope-path>...` from the
   repository root and keep its JSON output beside the contract. Add every
   `tests_to_run` entry to `verification`, run by type (`.sh` with bash, `.py`
   with python3, files under `clis/<module>/` with that module's test
   command); the list is a minimum, so module test commands still apply.
3. Initialize the subject:

   ```sh
   varde-workflow review init --subject <safe-id> --contract <contract.json> --repository <repo-root> --scope <path> --tier-evidence <risk-tier.json> --json
   ```

   Repeat repository-relative `--scope`. Add `--artifact <absolute-file>` for
   each external file, including planned ones (no directories or aliases).
   Missing, unreadable, or malformed `--tier-evidence` makes the subject high
   tier. `review check` also forces high tier from the stored contract, even
   when `data.subject.tier` reads low: a non-empty `open_choices`, a non-empty
   `shared_contracts` key (shared contracts: workflow instructions, CLI
   schemas), or no `assert:` marker in `verification`.

## 3. Get the pre-edit verdict

Low tier (`data.subject.tier` from `review inspect`) with none of the §2 step 3
contract triggers skips this entire section: `review check` accepts a missing
pre-edit record. High tier runs the steps below.

1. Give an agent with a clean, independent context:
   - subject id
   - repository
   - resolved `<working>` and `<knowledge>` paths
   - outcome and scope
   - assumptions and open questions
   - verification with expected results
   - structural risk
2. The reviewer loads `references/review-gate-record.md` before writing
   evidence in either phase and records its own verdict before any edit.

Rules for the verdict:

- Coordinators never enter reviewer records or substitute prose approval.
- A finding is not approval of its fix.
- Persist unresolved human choices; ask only when they block implementation,
  and do not reopen decisions the user already made.
- If no independent reviewer or required CLI operation is available, stop
  implementation: no self-approval, hand-edited record, or manual fallback.

## 4. Run checkpoints

Run `varde-workflow review check --subject <subject-id>` with:

- `--checkpoint start --json` before edits
- `--checkpoint resume --json` before resuming
- `--checkpoint complete --json` before reporting completion

Proceed only when it passes:

- exit 4: a gate blocker; resolve it or refresh evidence
- exit 3: an OCC conflict; re-inspect and retry
- exit 1: an infrastructure error, not a gate result

Transitions and `conclude` enforce the same checks before writing.

Material contract changes need a fresh independent verdict.

## 5. Complete with final review

Implementation review is always required, independent of tier.

1. Finish source, docs, and verification.
2. The reviewer inspects phase `implementation` and records evidence covering
   the whole current subject change, including `tier_confirmed`.
3. Run the complete checkpoint. Later edits to covered files need rerun checks
   and refreshed evidence.

Review agent documents with `varde-agent-doc-authoring`. High tier code uses
`varde-review report`. Low tier code: a clean-context reviewer inspects the
diff against the contract's outcome and verification and records via
`references/review-gate-record.md`, with no `varde-review report`.
Behavior-changing or risky review fixes need fresh independent approval;
others need targeted verification. Do not recursively invoke unrelated
reviews once findings and checks are resolved.
