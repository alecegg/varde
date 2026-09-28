# Plan Fundamentals

Checks run during the growth loop (`references/plan-grow-doc.md`) and the
closing sequence run once its exit criteria pass.

## External interface check

If a touched surface has existing consumers (exported API, CLI flag, env var,
CI config, shared type, a file others read), flag it explicitly and find them
— `dependents`/`blast_radius` with `varde-code` (`references/varde-code.md`),
else grep. Record them in Design and AC. Wider than expected is itself a
flag; fan-out across independent packages is a split candidate. Internal-only
changes skip this.

## Self-review

Empty `## Open Questions` is not done. Hunt placeholders (TBD, vague Design),
contradictions between decisions, scope the Solution implies but Non-goals
omits, and decisions admitting two implementations; add each as an Open
Question and continue.
If scope outside fenced code blocks adds a second case to a formerly
single-case model, makes a required field optional, or turns a derived or fixed
value into a choice, and `## Decisions so far` does not already resolve that
shift, add one Open Question asking whether to promote the general model or
add-alongside the old one and record its answer there; otherwise stay silent.

## Finalize

1. Derive the slug from the plan's title or problem (lowercase, hyphenated)
   without asking. Rename the directory to `<UTC-date>-<slug>`, keeping the
   draft's date; the plan id is its name. Use `git mv` when
   `git ls-files --error-unmatch <working>/plans/<old-plan-id>/plan.md`
   succeeds, else plain `mv`.
   Name the final id in the confirmation turn; the user may rename it.
2. **Review before confirming.** Apply `references/review-gates.md` to the
   persisted plan and initialize a subject before implementation:

   ```sh
   varde-workflow review init --plan <plan.md> --repository <repo-root> --scope <path> [--scope <path> ...] --json
   ```

   Give an independent agent the plan, returned subject id, scope, and resolved
   absolute `<working>`/`<knowledge>` paths. Ask it to find unstated
   assumptions, unresolved human choices, unverifiable criteria, and
   independently shippable changes. It inspects `pre-edit` and writes its own
   review record through `varde-workflow review record`; keep the subject id in
   plan Progress for build and resume. Apply findings and review every
   criterion per `references/plan-acceptance-criteria.md`. Investigate
   code-answerable unknowns; return human decisions to the interview. Several
   changes: follow `references/plan-splitting.md` instead of step 3. Preserve
   the approved verdict for build; materially changed plans need fresh
   inspection and independent approval.
3. Ask the **final completeness check** in one turn: every assumption the user
   has not yet seen and every change step 2 made, one line each, grouped by
   what it affects, high-impact first; point at the plan file and ask
   "Anything left to resolve before we finalize?" Silence on a line the user
   never saw is not confirmation. Wait for explicit confirmation.
4. After confirmation, no more questions or content changes. Run
   `varde-workflow validate <plan-dir>/plan.md --json` and fix diagnostics;
   the plan stays `backlog`. Legal states and moves:
   `references/varde-workflow-cli.md`.
5. `git check-ignore -q` the plan path: ignored → local only; tracked →
   commit only its directory.
6. Announce "Plan `<plan-id>` is ready — ask to build it."
