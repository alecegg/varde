---
topic: varde-prototype/storage-and-close
version: 1
summary: Pick the slug and storage path, run the rounds, and close a prototype session
---

1. Pick a kebab-case `<slug>` and state the storage path: `<working>/prototypes/<slug>/`, or `<working>/plans/<plan-id>/prototypes/<slug>/` when a plan owns the work. Ask only if that path already exists.
2. Resolve `<working>` once with `varde setup paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.
3. Run the track's rounds. Ask one topic per turn (up to 3 questions only as facets of one decision) as an inline numbered menu with a recommendation.
4. Close when the user is done: report the final file path and key decisions (Logic: name the module to lift). If the user asked to plan or build, start that route in the same turn, by using the skill tool or reading its skill file. Otherwise offer it and wait.
