<!-- kind: reference -->
# Agent document outcome

The finished document:

- states only structural contracts, safety boundaries, and preferences the agent cannot infer (validate: each line passes `criteria.md`, Cut or keep);
- keeps parallel items short and starts sentences with the verb or condition (validate: `varde learn check <file>` exits 0);
- flags environment-specific instructions for user review instead of changing them.

Report the word-count or tokenizer delta against the base ref, and the review verdict.
