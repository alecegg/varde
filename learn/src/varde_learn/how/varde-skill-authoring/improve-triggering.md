---
topic: varde-skill-authoring/improve-triggering
version: 1
summary: Tune the description and run trigger evals
---

Read `references/criteria.md` (Description wording). Tune the description toward user intent and indirect phrasings, with no negative clause and no other skill named.

Keep about 20 queries in `evals/trigger-queries.json`, 8-10 per label. Write them as real users write: file paths, personal context, typos, casual wording, and some that never name the domain. Should-not-trigger queries are near misses that share keywords but need another task; obvious negatives test nothing.

Tune on `--split train` failures only (a fixed 60/40 split stratified by label), generalize to the category instead of copying failed keywords, then confirm with `--split validation`. Keep the iteration with the best validation pass rate, usually within five. Read the summary's precision (false triggers) and recall (misses) beside pass counts; poor results on both can mean mislabeled queries.

Measure with `varde learn measure <skill> trigger <queries.json> --harness <harness> [--split train|validation]` (billed; get user approval first).
