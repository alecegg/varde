# Instruction value audit, part C

Scope: every agent-read `.md` file in `skills/varde-learn/`, `skills/varde-knowledge/`, `skills/varde-explore/`, `skills/varde-prototype/`, and `skills/varde-agent-doc-authoring/`. Excluded: FLOW.md, evals/, and skills/shared copies. 433 instruction units are scored with the shared 0-5 rubric. Line numbers are 1-based per file at commit 23bef57. `A/SKILL.md` refers to `skills/varde-agent-doc-authoring/SKILL.md`.

## 1. Units, least valuable first

| Score | Verdict | Location | Instruction | Why |
|---|---|---|---|---|
| 0 | cut | `skills/varde-agent-doc-authoring/references/criteria.md:3` | Authoring meets these criteria; review checks every item against them | Callers already say this; no behavior. |
| 0 | cut | `skills/varde-knowledge/references/note.md:15` | &lt;knowledge>/ is the root of a markdown knowledge bundle | Description only. |
| 0 | cut | `skills/varde-learn/references/diagnose.md:43` | Inspection is local, read-only, bounded | Description, no action. |
| 0 | cut | `skills/varde-learn/references/diagnose.md:47` | snapshot.digest identifies bundle; integrity check not authenticity | Internals and rationale. |
| 0 | cut | `skills/varde-learn/references/recurrence.md:3` | Run this when checking recurrence after adopted change | Restates SKILL.md route row. |
| 0 | cut | `skills/varde-learn/references/recurrence.md:16` | Each occurrence paired with latest adoption strictly before it | CLI internals. |
| 1 | merge→skills/varde-agent-doc-authoring/references/criteria.md:18 | `skills/varde-agent-doc-authoring/references/author.md:12` | Draft only what evidence makes non-default, meeting the criteria | Restates criteria keep-test and Evidence section just loaded. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/author.md:17` | Check the changed scope against the criteria | Duplicates step 3 'meeting the criteria'. |
| 1 | merge→skills/varde-agent-doc-authoring/references/criteria.md:43 | `skills/varde-agent-doc-authoring/references/author.md:21` | Report any execution-cost optimization to the user | criteria.md:43-48 already says report it, with required fields. |
| 1 | merge→skills/varde-agent-doc-authoring/references/criteria.md:50 | `skills/varde-agent-doc-authoring/references/criteria.md:29` | Cut generic background and stale environment facts | Covered by Cut-it items 'restates default' and 'rationale'. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/criteria.md:43` | Cut it if its value does not justify its costs | Restates the question just asked. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/criteria.md:61` | Structure it? Lay out what remains per Structure below | Pointer to the next section of the same file. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/criteria.md:72` | Use lists or tables for branching logic and sequences | Frontier-model default. |
| 1 | script | `skills/varde-agent-doc-authoring/references/criteria.md:84` | Measure prose blocks, list items, sections; optimize each item past target | Describes what check-length.py computes; agent only acts on output. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/criteria.md:102` | Confirm what the harness loads at startup, activation, by reference | Vague; names no concrete check. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/criteria.md:144` | One imperative action per step | Model default. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/criteria.md:164` | Collapse a triad spelled out three times into one leading word | Rare edge case; no evidence. |
| 1 | shorten | `skills/varde-agent-doc-authoring/references/review.md:14` | Items: instructions, steps, branches | Enumerates 'every item'; default. |
| 1 | shorten | `skills/varde-agent-doc-authoring/references/review.md:15` | Items: outputs and flows | Enumerates 'every item'; default. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/review.md:18` | Ground findings in locations and observed behavior | Model default for reviews; output format already requires location. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/review.md:33` | Avoid filler alternatives | Covered by 'distinct options'. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/specification.md:9` | allowed-tools optional, experimental | No Varde SKILL.md uses allowed-tools. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/specification.md:11` | Optional license, compatibility, metadata | Validator-owned; rarely used. |
| 1 | script | `skills/varde-agent-doc-authoring/references/specification.md:12` | Mapping keys unique; YAML merge overrides valid | Validator enforces; internals. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/specification.md:22` | Earn its permanent cost as a model-invocation trigger | Vague; restates criteria Worth-it. |
| 1 | cut | `skills/varde-agent-doc-authoring/references/specification.md:26` | Every allowed-tools tool should appear in body; unenforced | No skill uses allowed-tools; unenforced. |
| 1 | cut | `skills/varde-explore/SKILL.md:13` | It saves an HTML file under &lt;working>/explanations/ by default | Dup of explain.md:26. |
| 1 | cut | `skills/varde-explore/SKILL.md:23` | Outside the repo, use plain file ops instead of git | Boilerplate; no git writes in explore. |
| 1 | script | `skills/varde-knowledge/references/handoff-snapshot.md:3` | Hash current contents incl staged and unstaged edits | Script behavior; agent only calls it. |
| 1 | shorten | `skills/varde-knowledge/references/handoff-snapshot.md:6` | Prints {path, hash} entries, path . for file, skipped_symlinks | Output description. |
| 1 | cut | `skills/varde-knowledge/references/note.md:7` | A known note: read it directly | Default. |
| 1 | cut | `skills/varde-learn/references/capture.md:12` | Text filter is case-insensitive literal substring | CLI --help states it. |
| 1 | cut | `skills/varde-learn/references/capture.md:33` | Appending keeps the existing item's scope and status | CLI internals. |
| 1 | cut | `skills/varde-learn/references/capture.md:34` | Confirm the occurrence with friction show | add --json already returns IDs; extra tool call. |
| 1 | cut | `skills/varde-learn/references/diagnose-capture.md:3` | Load only after diagnosis saved report with verified evidence | Caller diagnose.md:170 owns the load condition. |
| 1 | script | `skills/varde-learn/references/diagnose-capture.md:11` | Never invent event time, cwd, repo root, HEAD, native ID | Incident schema has no such fields; CLI derives them. |
| 1 | shorten | `skills/varde-learn/references/diagnose-capture.md:21` | Strict JSON; unknown fields rejected; 64 KiB file, 8 KiB evidence | CLI validates and errors; self-correcting. |
| 1 | cut | `skills/varde-learn/references/diagnose-capture.md:54` | Returns disposition created/already-recorded, at, cwd, null repo_root/head_sha; retries idempotent | CLI output description. |
| 1 | cut | `skills/varde-learn/references/diagnose-capture.md:58` | Example capture JSON output | CLI output description. |
| 1 | cut | `skills/varde-learn/references/diagnose-capture.md:68` | Prefer a verified native event ID | Agent copies anchor from inspect; no choice to make. |
| 1 | cut | `skills/varde-learn/references/diagnose-capture.md:69` | Fallback JSONL line position and digest; never fabricate native ID | CLI/inspect produce anchors; dup of L11. |
| 1 | cut | `skills/varde-learn/references/diagnose-quick.md:5` | Whole-session request uses diagnose.md incl. analyst rule | Dup of SKILL.md route and L16. |
| 1 | merge→skills/varde-learn/references/diagnose.md:95 | `skills/varde-learn/references/diagnose-toz.md:16` | Improvements go in bounded recommendations, which authorize no edits | Dup of diagnose.md 'recommend without applying'. |
| 1 | cut | `skills/varde-learn/references/diagnose.md:29` | --snapshot-out never overwrites; choose new private path | CLI errors on reuse; location dup of L13. |
| 1 | cut | `skills/varde-learn/references/diagnose.md:31` | Read data.overlap, coverage, session, children, records | Agent reads returned JSON anyway. |
| 1 | merge→skills/varde-learn/references/diagnose.md:74 | `skills/varde-learn/references/diagnose.md:93` | Keep correlation and hypotheses out of Observations | Template section labels already say this. |
| 1 | cut | `skills/varde-learn/references/diagnose.md:94` | Treat confidence as evidential support, not causal certainty | Rationale-level nuance. |
| 1 | merge→skills/varde-learn/references/diagnose.md:33 | `skills/varde-learn/references/diagnose.md:138` | Explicit --session/--path do not bypass when aliasing current | Restates 'select from overlap, never selector'. |
| 1 | cut | `skills/varde-learn/references/diagnose.md:140` | Unknown overlap not proof of past; only not_current inline | Restates L135 'current or unknown'. |
| 1 | cut | `skills/varde-learn/references/diagnose.md:143` | Do not run mandatory seven-agent pass or separate grading judge | Guards a historical pattern; no current trigger. |
| 1 | merge→skills/varde-learn/references/diagnose.md:95 | `skills/varde-learn/references/diagnose.md:171` | Capture never authorizes source or item status changes | Dup of L95. |
| 1 | merge→skills/varde-learn/references/distill.md:15 | `skills/varde-learn/references/distill.md:4` | One incident can be recorded but cannot support a change | Dup of step 2 threshold. |
| 1 | shorten | `skills/varde-learn/references/evals.md:3` | Output vs Trigger eval table | Definitional; one line enough. |
| 1 | cut | `skills/varde-learn/references/evals.md:9` | Static checks need no session | Obvious clarification. |
| 1 | cut | `skills/varde-learn/references/reconcile.md:3` | Recorded summary is not proof the problem is fixed | Rationale; step 2 enforces. |
| 1 | cut | `skills/varde-prototype/SKILL.md:19` | Production -> varde-change; running UI report -> varde-review | Dup of description 'Not for' and L8. |
| 1 | cut | `skills/varde-prototype/SKILL.md:44` | &lt;knowledge> resolution and 'outside repo plain file ops' | Unused in prototype; boilerplate. |
| 1 | merge→skills/varde-prototype/SKILL.md:24 | `skills/varde-prototype/references/logic-track.md:31` | Each round, ask about one missing action/scenario/field | Dup of SKILL.md one-topic rule. |
| 1 | cut | `skills/varde-prototype/references/visual-track.md:37` | Add only local interactions that help evaluate flow or state | Default. |
| 1 | merge→skills/varde-prototype/SKILL.md:24 | `skills/varde-prototype/references/visual-track.md:40` | One targeted question per round, or refine and state assumption | Dup of SKILL.md one-topic rule. |
| 2 | script | `skills/varde-agent-doc-authoring/SKILL.md:21` | Keep each skill independently usable: every reference it loads is its own | Repo AGENTS.md rule 1 owns it; check-refs.sh enforces in varde. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/author.md:8` | Ask about environment and tools actually used | Helpful elicitation prompt. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/author.md:9` | Ask about failures or near-misses and fixes | Helpful elicitation prompt. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/author.md:10` | Ask about conventions a newcomer gets wrong | Helpful elicitation prompt. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/author.md:11` | Ask about steps done by hand or often forgotten | Helpful elicitation prompt. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/author.md:14` | Final pass on changed files, short of full review | Scopes effort; prevents running full review by default. |
| 2 | script | `skills/varde-agent-doc-authoring/references/author.md:18` | Check every changed pointer and each file's kind | skill-flow.py already reports pointers and kinds. |
| 2 | merge→skills/varde-agent-doc-authoring/references/criteria.md:51 | `skills/varde-agent-doc-authoring/references/criteria.md:16` | State the goal and a default; let the agent choose the method | Same test as Cut-it item 'spells out a method'. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:17` | Give exact commands only for fragile operations | Useful default against over-prescription. |
| 2 | shorten | `skills/varde-agent-doc-authoring/references/criteria.md:19` | When effect consequential but unclear, compare small prompt set with and without | Rarely run; point to varde-learn evals instead. |
| 2 | merge→skills/varde-agent-doc-authoring/references/author.md:5 | `skills/varde-agent-doc-authoring/references/criteria.md:24` | Ground project-specific rules in evidence: runbooks, schemas, history, incidents, reviews | Overlaps author.md step 2 evidence gathering. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:28` | Record only corrections the repository does not make obvious | Blocks repo-derivable facts; mild overlap with L50. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:30` | Keep a skill to one coherent task | Scope heuristic; cheap failure. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:35` | Answer these in order, in one pass, for every item and checker flag | Orders the audit; modest value. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:51` | Cut when it spells out a method where goal and default suffice | Useful cut criterion; dup of L16. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:53` | Cut when it explains rationale the agent does not need | Useful cut criterion. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:54` | Cut when it guards an edge case with no evidence of failure | Useful cut criterion. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:55` | Cut when it describes internals of a script or CLI agent only calls | Useful cut criterion. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:58` | Leave one line naming skill-root-relative invocation; templates or validators for outputs | Helpful default for scripted steps. |
| 2 | merge→skills/varde-agent-doc-authoring/references/criteria.md:71 | `skills/varde-agent-doc-authoring/references/criteria.md:63` | Success is fewer words; structuring alone only moves the problem | Same point as L71 'only moves the length'. |
| 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:67` | Parallel items one per line under purpose lead-in at 4+ or 3 multiword | check-length.py already warns on inline lists with these thresholds. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:70` | Keep parallel items to a phrase, rule items to one or two sentences | Concise style default. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:73` | Put a conditional branch in its own section after the main path | Helpful layout default. |
| 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:78` | End line items with punctuation; blank line after list; lazy continuation rationale | check-length.py warns lazy continuations; drop rationale sentence. |
| 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:94` | Unit sentences: target 3, reason 4-5, defect 6+ | Script computes; agent needs only the 'needs a reason' band. |
| 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:95` | Section words: 250 / 251-400 / over 400 | Script computes. |
| 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:96` | File prose share: 40% / 41-60% / over 60% | Script computes. |
| 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:98` | High prose share means steps or lists still written as sentences | Fix hint; belongs in script message. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:120` | Sharing and frequency do not decide kind; if in doubt, procedure | Tie-breaker; cheap. |
| 2 | shorten | `skills/varde-agent-doc-authoring/references/criteria.md:129` | Name a path after 'skip' in entry file to drop it from route metrics | Niche metrics feature; one clause suffices. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:137` | Several invocation shapes: entry-point table; cells name an action | Layout default. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:142` | One numbered workflow per invocation type | Layout default. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:145` | One primary procedure per step, inline or in a reference | Layout default. |
| 2 | merge→skills/varde-agent-doc-authoring/references/criteria.md:110 | `skills/varde-agent-doc-authoring/references/criteria.md:149` | Keep short procedures and gates inline | Same as 'merge other references into caller'. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:150` | Keep literal templates inline or in assets/ | Layout default. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:153` | Make completion observable; explicit handoff only with evidence | Guards against unneeded handoff steps. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:158` | State actions positively; prohibitions only for hard boundaries, with alternative | Wording default with some value. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:160` | Open sentences with verb or condition | Wording default. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:161` | Name mechanisms concretely | Wording default with example. |
| 2 | merge→skills/varde-agent-doc-authoring/references/criteria.md:50 | `skills/varde-agent-doc-authoring/references/criteria.md:163` | Cut guidance that names no observable action | Overlaps Cut-it list. |
| 2 | shorten | `skills/varde-agent-doc-authoring/references/review.md:3` | Audit adversarially every item in scope; trace behavior and loading | Posture line; overlaps step 1.3. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/review.md:16` | Items: references and scripts | Easily-skipped item class. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/review.md:17` | Items: templates and evals | Easily-skipped item class. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/review.md:20` | Mark untested effects as uncertain | Honesty default with small cost. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/review.md:24` | Order findings from most to least in need of fix | Helpful ordering. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/review.md:32` | List retained items briefly; no invented fixes | Ensures full-inventory coverage. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/review.md:49` | Apply, verify, mark Fixed naming applied option | Traceability default. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/review.md:56` | Agent-initiated: return list to that agent | Near-default. |
| 2 | script | `skills/varde-agent-doc-authoring/references/specification.md:7` | name: 1-64 lowercase, digits, single hyphens; matches directory | validate-frontmatter.py enforces; self-correcting. |
| 2 | merge→skills/varde-agent-doc-authoring/references/specification.md:18 | `skills/varde-agent-doc-authoring/references/specification.md:8` | description: non-empty, max 1024; what, when, trigger terms | Length enforced by validator; guidance dups wording list. |
| 2 | keep | `skills/varde-agent-doc-authoring/references/specification.md:19` | Say when skill applies, incl. indirect phrasings | Triggering helper; overlaps L8. |
| 2 | merge→skills/varde-agent-doc-authoring/references/author.md:13 | `skills/varde-agent-doc-authoring/references/specification.md:30` | Validate with validate-frontmatter.py (--json; several paths) | author.md:13 already requires the run. |
| 2 | keep | `skills/varde-explore/SKILL.md:18` | Options: name each, tradeoffs, recommend one | Near-default; user global pref. |
| 2 | keep | `skills/varde-explore/references/explain.md:4` | Other format requested: answer in chat in that format | Default. |
| 2 | keep | `skills/varde-explore/references/explain.md:11` | Git ref/range/PR -> change explanation | Shape routing; inferable. |
| 2 | keep | `skills/varde-explore/references/explain.md:12` | Area keyword or path -> area explanation | Shape routing; inferable. |
| 2 | keep | `skills/varde-explore/references/explain.md:13` | Named alternatives -> options comparison | Shape routing; inferable. |
| 2 | keep | `skills/varde-explore/references/explain.md:15` | Ambiguous ref/path: ask numbered menu; else infer and state shape | Default. |
| 2 | keep | `skills/varde-explore/references/explain.md:24` | Area: recent commits; options: code each touches | Default context gathering. |
| 2 | keep | `skills/varde-explore/references/explain.md:36` | Section Background | Section spec. |
| 2 | keep | `skills/varde-explore/references/explain.md:37` | Section Intuition: analogies, invariants | Section spec. |
| 2 | keep | `skills/varde-explore/references/explain.md:44` | Section Options | Section spec. |
| 2 | keep | `skills/varde-explore/references/explain.md:45` | Section Tradeoffs against shared constraints | Section spec. |
| 2 | shorten | `skills/varde-knowledge/SKILL.md:18` | Outside the repo, use plain file ops instead of git | Relevant for git mv; wording ambiguous. |
| 2 | merge→skills/varde-knowledge/references/reflect.md:10 | `skills/varde-knowledge/SKILL.md:20` | Friction belongs to varde-learn; switch by name, don't import references | Description 'Not for friction' plus reflect step 1 cover it. |
| 2 | keep | `skills/varde-knowledge/references/handoff-resume.md:13` | Re-read unknown targets, modified plan log, modified knowledge | Reasonable default. |
| 2 | script | `skills/varde-knowledge/references/handoff-resume.md:32` | Legacy link: git root checks, git diff head_sha; nonempty modified | Legacy path; could be a script mode or dropped. |
| 2 | shorten | `skills/varde-knowledge/references/handoff-resume.md:36` | Missing baseline, other repo, external, dir, failure: unknown; drop 'because' rationale | Catch-all label; rationale unneeded. |
| 2 | keep | `skills/varde-knowledge/references/handoff-write.md:10` | Tailor What's left and Suggested next skill to named focus | Default. |
| 2 | keep | `skills/varde-knowledge/references/handoff-write.md:24` | Prefer explicit file links; never imply full-directory coverage | Helpful default. |
| 2 | keep | `skills/varde-knowledge/references/handoff-write.md:65` | Body does not restate frontmatter | Minor dedupe. |
| 2 | keep | `skills/varde-knowledge/references/note.md:11` | Read a note in full only after discovery identifies it | Token default. |
| 2 | merge→skills/varde-knowledge/references/reflect.md:12 | `skills/varde-knowledge/references/note.md:30` | Keep only lasting decisions, patterns, definitions | Dup of skill purpose and reflect filter. |
| 2 | keep | `skills/varde-knowledge/references/note.md:36` | type: required, non-empty | Template shows it. |
| 2 | keep | `skills/varde-knowledge/references/note.md:42` | title only when slug is poor display name | Minor default. |
| 2 | merge→skills/varde-knowledge/references/note.md:36 | `skills/varde-knowledge/references/note.md:45` | Frontmatter example block | Duplicates field bullets. |
| 2 | keep | `skills/varde-knowledge/references/note.md:59` | definition: description is the definition; body only for usage | Type body rule. |
| 2 | keep | `skills/varde-knowledge/references/note.md:61` | pattern: rule in short bullets; examples only if prevent misuse | Type body rule. |
| 2 | keep | `skills/varde-knowledge/references/note.md:81` | Rename or move with git mv | Default; preserves history. |
| 2 | merge→skills/varde-knowledge/references/note.md:78 | `skills/varde-knowledge/references/reconcile.md:5` | Correct in place; gone subject -> deprecated | Deprecation rule owned by note.md. |
| 2 | keep | `skills/varde-knowledge/references/reconcile.md:7` | Read note, then code in paths; compare by hand | Default procedure. |
| 2 | keep | `skills/varde-knowledge/references/reflect.md:3` | Runs at session boundary: ending, wrap-up, plan completed | Trigger context. |
| 2 | keep | `skills/varde-knowledge/references/reflect.md:22` | Check old items only when asked; route friction reconcile to varde-learn | Scope limiter. |
| 2 | merge→AGENTS.md sandbox posture | `skills/varde-learn/SKILL.md:22` | On sandbox denial retry once escalated, then report | Boilerplate repeated in 5 skills and AGENTS.md. |
| 2 | merge→skills/varde-learn/SKILL.md | `skills/varde-learn/references/capture.md:12` | Page with --offset/--limit; show until meta.truncated false | Paging rule repeated in 4 learn references. |
| 2 | keep | `skills/varde-learn/references/capture.md:36` | Evidence specific: command, what happened, immediate cost | Quality default. |
| 2 | keep | `skills/varde-learn/references/capture.md:37` | Store records repo/Git context; do not invent it in evidence | Prevents duplicated/fabricated context. |
| 2 | keep | `skills/varde-learn/references/diagnose-capture.md:16` | Confirm no matching friction item already represents it | Chooses existing vs new item. |
| 2 | merge→skills/varde-learn/references/diagnose-capture.md:29 | `skills/varde-learn/references/diagnose-capture.md:22` | Copy digest, thread_id, anchor; incident_kind one of three; item mode | Template placeholders already encode mapping; keep kind enum only. |
| 2 | keep | `skills/varde-learn/references/diagnose-capture.md:64` | Conflict or validation error is not a successful capture | Prevents claiming success; mild. |
| 2 | merge→skills/varde-learn/references/diagnose.md:96 | `skills/varde-learn/references/diagnose-capture.md:72` | Rewritten, inherited, uncertain anchors remain report-only | Dup of L8 and diagnose.md report rules. |
| 2 | keep | `skills/varde-learn/references/diagnose-capture.md:73` | Never relabel an event to add an occurrence | CLI dedupes across kinds anyway; self-correcting. |
| 2 | keep | `skills/varde-learn/references/diagnose-quick.md:9` | State what evidence shows, citing message or tool result | Citation default. |
| 2 | keep | `skills/varde-learn/references/diagnose-quick.md:16` | Session-wide or historical request: switch to diagnose.md | Escalation route; keep one of L5/L16. |
| 2 | merge→skills/varde-learn/references/diagnose.md:104 | `skills/varde-learn/references/diagnose-toz.md:10` | Current/unknown overlap: verified links, frozen pre-cutoff excerpts; cite handles | Restates diagnose.md cutoff rules. |
| 2 | keep | `skills/varde-learn/references/diagnose-toz.md:22` | Captures supplement native witnesses; unavailable -> report gap and continue | Degrade-gracefully default. |
| 2 | merge→AGENTS.md sandbox posture | `skills/varde-learn/references/diagnose.md:10` | On failure retry escalated once, then ask for path | Boilerplate repeated across skills. |
| 2 | keep | `skills/varde-learn/references/diagnose.md:22` | --harness and exactly one of --current/--session/--path | CLI rejects bad combos; self-correcting. |
| 2 | shorten | `skills/varde-learn/references/diagnose.md:51` | Before report for current/unknown overlap, follow procedure below | Forward pointer; reorder sections instead. |
| 2 | keep | `skills/varde-learn/references/diagnose.md:62` | Omit a section only when it does not apply | Template default. |
| 2 | keep | `skills/varde-learn/references/diagnose.md:91` | Bounded triage covers failures, repeated work, deviations, time/token signals | Coverage checklist. |
| 2 | keep | `skills/varde-learn/references/diagnose.md:148` | Pass: complaint or triage question | Handoff item. |
| 2 | keep | `skills/varde-learn/references/diagnose.md:149` | Pass: relevant workflow rules | Handoff item. |
| 2 | keep | `skills/varde-learn/references/diagnose.md:150` | Pass: coverage metadata and known gaps | Handoff item. |
| 2 | keep | `skills/varde-learn/references/diagnose.md:152` | Pass: request anchored observations separate from hypotheses | Handoff item. |
| 2 | keep | `skills/varde-learn/references/diagnose.md:164` | New coordinator reusing bundle rechecks identity; delegate if overlap not excluded | Edge case; no failure evidence cited. |
| 2 | merge→skills/varde-learn/SKILL.md | `skills/varde-learn/references/distill.md:12` | Follow next_offset while truncated; finish show pages before counting | Paging rule repeated; 'before counting' is the unique bit. |
| 2 | keep | `skills/varde-learn/references/distill.md:20` | Inspect source; classify add/tighten/simplify | Helpful framing. |
| 2 | keep | `skills/varde-learn/references/distill.md:24` | Offer before/after evaluation on identical cases | Useful default; overlaps step 5. |
| 2 | keep | `skills/varde-learn/references/distill.md:26` | Present: shared failure mode | Output item. |
| 2 | keep | `skills/varde-learn/references/distill.md:28` | Present: expected impact as hypothesis, risks | Output item. |
| 2 | keep | `skills/varde-learn/references/distill.md:29` | Present: items that would become promoted | Output item. |
| 2 | merge→skills/varde-learn/references/distill.md:37 | `skills/varde-learn/references/distill.md:33` | If evals approved, run before cases | Merge with L37 into one before/after line. |
| 2 | keep | `skills/varde-learn/references/distill.md:37` | If evals approved, run after cases and compare | Sequencing. |
| 2 | shorten | `skills/varde-learn/references/distill.md:52` | Recording promotes atomically; no separate status command; report failure | Stops redundant set-status; drop 'nothing partial' clause. |
| 2 | keep | `skills/varde-learn/references/evals.md:19` | Start with 2-3 cases incl. an edge case | Cost default. |
| 2 | keep | `skills/varde-learn/references/evals.md:20` | Review outputs before writing assertions | Quality default. |
| 2 | keep | `skills/varde-learn/references/evals.md:24` | Results apply only to selected harness/model, no fallback | Interpretation caveat. |
| 2 | script | `skills/varde-learn/references/evals.md:39` | List changed skills with git diff | cut | sort -u | Deterministic; fits a script or CLI flag. |
| 2 | keep | `skills/varde-learn/references/evals.md:51` | Replace always-pass/fail/unverifiable assertions | Quality default. |
| 2 | keep | `skills/varde-learn/references/evals.md:67` | Positives pass above 0.5; repeat uncertain with --runs 3 | Interpretation default. |
| 2 | keep | `skills/varde-learn/references/evals.md:69` | Expand to ~20 x 3 only when misfires persist | Cost default. |
| 2 | merge→skills/varde-learn/SKILL.md | `skills/varde-learn/references/reconcile.md:11` | show pages occurrences and history; continue --offset until not truncated | Paging rule repeated. |
| 2 | keep | `skills/varde-learn/references/recurrence.md:4` | Reports historical occurrences; does not establish still present | Interpretation caveat. |
| 2 | keep | `skills/varde-learn/references/recurrence.md:15` | Report adoption_id, summary, item, timestamp, evidence per row | Output default. |
| 2 | keep | `skills/varde-prototype/SKILL.md:18` | Ambiguous: pages -> Visual; states -> Logic; say which | Tie-breaker. |
| 2 | keep | `skills/varde-prototype/SKILL.md:37` | Run the track's rounds per its reference | Step pointer; dup of table. |
| 2 | keep | `skills/varde-prototype/references/logic-track.md:15` | Title and question paragraph | Shell section. |
| 2 | keep | `skills/varde-prototype/references/logic-track.md:19` | Free-play button per action | Shell section. |
| 2 | keep | `skills/varde-prototype/references/logic-track.md:32` | Plain style: typography, spacing, one accent, no animation | Style preference; cheap. |
| 2 | keep | `skills/varde-prototype/references/logic-track.md:37` | Add no tests | Prototype scope default. |
| 2 | keep | `skills/varde-prototype/references/logic-track.md:38` | In-memory state unless persistence is the question | Scope default. |
| 2 | keep | `skills/varde-prototype/references/visual-track.md:8` | Identify user, task, primary action, constraints; ask only material gaps | Default design practice. |
| 2 | keep | `skills/varde-prototype/references/visual-track.md:11` | Realistic page context; cover loading/empty/error/success states | Default design practice. |
| 2 | keep | `skills/varde-prototype/references/visual-track.md:20` | 2-3 close or 3-5 distinct; default 3; state count | Default. |
| 2 | keep | `skills/varde-prototype/references/visual-track.md:22` | Vary hierarchy, layout, primary action; same content | Default. |
| 2 | merge→skills/varde-prototype/SKILL.md:8 | `skills/varde-prototype/references/visual-track.md:34` | Never edit production source in this track | Dup of SKILL.md production boundary. |
| 2 | keep | `skills/varde-prototype/references/visual-track.md:35` | Semantic elements, labels, focus, contrast, responsive | Accessibility default. |
| 2 | keep | `skills/varde-prototype/references/visual-track.md:49` | Refine at primary and narrow viewports | Default. |
| 2 | keep | `skills/varde-prototype/references/visual-track.md:51` | Save and inspect screenshots beside prototype | Default. |
| 2 | keep | `skills/varde-prototype/references/visual-track.md:53` | Report what could not be inspected and continue | Honesty default. |
| 3 | keep | `skills/varde-agent-doc-authoring/SKILL.md:17` | Improve triggering -> specification.md plus sibling SKILL.md descriptions | Reading siblings prevents description collisions; not default behavior. |
| 3 | keep | `skills/varde-agent-doc-authoring/SKILL.md:22` | Point to local files via relative link or backticked references/scripts/assets path; bare paths unchecked | skill-flow.py only sees these forms; else FLOW/route metrics miss edges. |
| 3 | script | `skills/varde-agent-doc-authoring/SKILL.md:25` | Check authored files for stray literal &lt;/content> lines | Evidence-based harness artifact; no script checks it; add to check-length.py. |
| 3 | shorten | `skills/varde-agent-doc-authoring/references/author.md:5` | Gather evidence; without source, offer runbook or ask one question at a time | Prevents drafting generic default-restating docs; drop 'would only restate' rationale. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/author.md:16` | Run check-length.py | Deterministic limit check; cheap, catches defects prose misses. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:9` | Prescribe structural contracts: layout, paths, formats, CLI invocations, state transitions | Core rubric; without it reviews keep advisory prose. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:11` | Prescribe safety boundaries: destructive, irreversible, outward-facing actions | Core rubric; protects safety rules from over-cutting. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:12` | Prescribe stated preferences the agent cannot infer | Core rubric; protects user preferences from cuts. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:18` | Keep an instruction only if the agent would likely fail without it | The key value test; drives every cut. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:38` | Worth it? weigh value against reading cost (tokens x frequency) and following cost | Non-default cost model; without it audits ignore execution cost. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:43` | Execution-cost optimization: report cost, value, cheaper alternative to user | User preference: behavior-changing cuts need a user decision. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:50` | Cut when it restates a default the agent follows unprompted | Primary cut criterion. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:52` | Cut when it repeats a rule another file owns; point instead | Prevents drift from duplicated rules. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:56` | Script it: move deterministic work into bundled PEP 723 script or CLI flag | Non-default direction; drives scripting of repeated work. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:74` | Numbered step headings when content block; numbered items are sub-steps, bullets information | House convention the agent cannot infer. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:89` | check-length.py exits 1 only on defects; also warns inline lists, lazy continuations | Tells agent warnings are non-fatal but still need action. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:103` | Make the entry file a run sheet of always-needed instructions | Drives load-cost reduction; non-default. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:105` | Split references only at real ~400-word branch or conditional path many runs skip | Prevents reference sprawl; concrete threshold. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:106` | Keep sequential content in one file; state load condition; prefix child filenames with parent's name | Naming convention not inferable; misplaced under 'Split only' lead-in. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:110` | Merge other references and chains into caller; state each rule once and point | Drives consolidation; overlaps L52. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:112` | Shallow tree: SKILL.md -> entry -> leaves; leaves never point to each other | Structural loading contract checked by skill-flow.py. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:118` | Procedure vs Reference kind definitions | Needed to apply the kind marker correctly. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:127` | Map loading with skill-flow.py; chain/single-caller = merge candidates; warning = route too big | Tells how to act on script output. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:151` | End SKILL.md with a short ## Gotchas section of always-needed corrections | House convention; contradicts L159 'keep gotchas inline'. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:165` | Keep lines unambiguous; accuracy outranks brevity | Counterweight preventing over-cutting of contracts. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:170` | Measure with wc -w before/after and report delta; small fixes state benefit | User preference for honest metrics. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:9` | Inventory scope; run check-length.py and skill-flow.py for a whole skill | Deterministic checks catch defects cheaply. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:12` | Check every item against criteria, answering Optimize questions in order | Core review procedure. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:19` | Separate correctness defects from value judgments | Output contract; mixes otherwise obscure real bugs. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:26` | Per finding: location, evidence, value/cost judgment | Output format contract. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:29` | One fix when obvious, else three distinct options with recommendation | User preference for decision format. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:35` | List execution-cost optimizations in own group as user options | Keeps behavior-changing items out of auto-apply. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:46` | Never apply an execution-cost optimization | Prevents behavior change without user decision. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:46` | Apply fixes that clearly preserve functionality and accuracy | User preference: apply clear fixes without asking. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:54` | User-initiated: save list as Markdown in workspace or given location; summary and link | Output location contract. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/review.md:58` | Delegating a user request does not change its origin | Prevents delegated reviews never being saved. |
| 3 | keep | `skills/varde-agent-doc-authoring/references/specification.md:18` | Description concrete, user-worded, leading with outcome verbs | Triggering quality depends on it. |
| 3 | keep | `skills/varde-explore/SKILL.md:17` | Ground answers in files read; cite path:line | Citation format preference. |
| 3 | keep | `skills/varde-explore/SKILL.md:19` | Structure questions: load varde-code-cli.md | Conditional tool routing. |
| 3 | shorten | `skills/varde-explore/SKILL.md:23` | Resolve &lt;working>/&lt;knowledge> via varde-workflow paths | Only explain mode needs &lt;working>; &lt;knowledge> unused. |
| 3 | keep | `skills/varde-explore/SKILL.md:25` | Explicit plan/build request: start varde-change same turn; else offer and wait | User preference on handoff. |
| 3 | keep | `skills/varde-explore/references/explain.md:20` | Load varde-code-cli.md for unknown scope or several targets | Conditional load. |
| 3 | keep | `skills/varde-explore/references/explain.md:22` | PR diff via gh pr diff or pull/&lt;n>/head against PR base, not checkout | Prevents wrong diff base. |
| 3 | keep | `skills/varde-explore/references/explain.md:38` | Code (hunks with callers) or How It Works (files, entry, data flow) | Core content spec. |
| 3 | keep | `skills/varde-explore/references/explain.md:46` | Section Recommendation and remaining uncertainty | User preference for a recommendation. |
| 3 | keep | `skills/varde-knowledge/references/handoff-resume.md:8` | One candidate: resume; several: numbered menu with recommendation | Avoids needless question; format preference. |
| 3 | keep | `skills/varde-knowledge/references/handoff-resume.md:10` | Label links; report differing branch/HEAD/pwd as modified context | Surfaces stale context before acting. |
| 3 | keep | `skills/varde-knowledge/references/handoff-resume.md:15` | Summarize, propose next steps, wait for confirmation | Prevents acting on stale handoff without consent. |
| 3 | keep | `skills/varde-knowledge/references/handoff-resume.md:21` | Resolve targets independently of handoff location; legacy relative vs cwd; labels never block | Resolution contract. |
| 3 | keep | `skills/varde-knowledge/references/handoff-resume.md:25` | Missing target: missing | Label vocabulary. |
| 3 | keep | `skills/varde-knowledge/references/handoff-resume.md:26` | integrity none: unknown; re-read before acting | Label vocabulary plus action. |
| 3 | keep | `skills/varde-knowledge/references/handoff-snapshot.md:4` | Snapshot a directory only for a small owned artifact folder | Prevents huge hash lists. |
| 3 | keep | `skills/varde-knowledge/references/handoff-write.md:17` | kind file: file path | Kind vocabulary. |
| 3 | keep | `skills/varde-knowledge/references/handoff-write.md:18` | kind plan: owning plan; its log holds history | Kind vocabulary; drop log clause. |
| 3 | keep | `skills/varde-knowledge/references/handoff-write.md:19` | kind review: review folder or findings file | Kind vocabulary. |
| 3 | keep | `skills/varde-knowledge/references/handoff-write.md:20` | kind knowledge: harvested note; reference, never restate | Kind vocabulary plus no-duplication rule. |
| 3 | keep | `skills/varde-knowledge/references/handoff-write.md:22` | integrity none default; snapshot with content_hashes when requested or long-lived | Cost default; lacks pointer to snapshot script. |
| 3 | keep | `skills/varde-knowledge/references/handoff-write.md:26` | Resolve independently, store absolute paths, drop and report missing | Resume needs absolute paths. |
| 3 | keep | `skills/varde-knowledge/references/handoff-write.md:33` | description: one line | Frontmatter field. |
| 3 | keep | `skills/varde-knowledge/references/handoff-write.md:34` | timestamp ISO-8601 UTC | Newest-first sort key. |
| 3 | keep | `skills/varde-knowledge/references/handoff-write.md:41` | Handoff body template | Consistent resumable structure. |
| 3 | keep | `skills/varde-knowledge/references/note.md:8` | Broad discovery: start from generated index.md maps | Agent would not know maps exist. |
| 3 | keep | `skills/varde-knowledge/references/note.md:9` | Precise term: ranked search per varde-workflow-cli.md, else grep | Tool routing. |
| 3 | keep | `skills/varde-knowledge/references/note.md:37` | description: one sentence, used in search snippets | Search depends on it. |
| 3 | keep | `skills/varde-knowledge/references/note.md:40` | verified: add on human sign-off; leave generated | Provenance contract. |
| 3 | keep | `skills/varde-knowledge/references/note.md:43` | paths: code described (used by reconcile) | Reconcile needs it. |
| 3 | keep | `skills/varde-knowledge/references/note.md:63` | decision: What/Why/Constraints template | Consistent decision format. |
| 3 | keep | `skills/varde-knowledge/references/note.md:80` | Delete only incorrect content | Destructive-action limit. |
| 3 | keep | `skills/varde-knowledge/references/note.md:87` | Link unwritten note only if written this session | Prevents dangling links. |
| 3 | keep | `skills/varde-knowledge/references/reconcile.md:3` | Edit only with code evidence; ask if ambiguous | Prevents unsupported edits to committed knowledge. |
| 3 | keep | `skills/varde-knowledge/references/reflect.md:8` | Run in order; knowledge before handoff | Handoff needs note paths. |
| 3 | keep | `skills/varde-knowledge/references/reflect.md:10` | Capture each real obstacle via varde-learn; skip when none | Cross-skill routing. |
| 3 | keep | `skills/varde-knowledge/references/reflect.md:12` | Record what another session needs; prefer updates; skip obvious/temporary | Filters knowledge noise. |
| 3 | keep | `skills/varde-knowledge/references/reflect.md:16` | Handoff only when something left; else none unless asked | User preference against noise handoffs. |
| 3 | keep | `skills/varde-knowledge/references/reflect.md:26` | Report knowledge paths, handoff ID, Learn IDs or failure | Output contract. |
| 3 | keep | `skills/varde-learn/references/capture.md:3` | Record only a problem that happened; not predicted risk or lesson | Keeps store evidence-based; else distill overfits. |
| 3 | keep | `skills/varde-learn/references/capture.md:6` | Search open items with distinctive phrase (friction list --text) | Dedupe before add; exact CLI. |
| 3 | keep | `skills/varde-learn/references/capture.md:15` | Append only for same obstacle, not a related topic | Wrong merges corrupt recurrence counts. |
| 3 | keep | `skills/varde-learn/references/capture.md:31` | Repo-scoped by default; --global for cross-project skill/tool | Scope choice not inferable. |
| 3 | merge→skills/varde-learn/references/diagnose.md:96 | `skills/varde-learn/references/diagnose-capture.md:8` | Event eligible only if identity revalidated and precedes verified cutoff; else report-only | Prevents capturing contaminated events; dup of report rules. |
| 3 | keep | `skills/varde-learn/references/diagnose-capture.md:17` | One canonical triggering event; ambiguous grouping stays in report | Prevents inflated occurrence counts. |
| 3 | keep | `skills/varde-learn/references/diagnose-capture.md:19` | Failed-tool: inspect exact anchored result; status label alone not proof | Prevents false failed-tool captures. |
| 3 | keep | `skills/varde-learn/references/diagnose-capture.md:62` | Record each result in report; refresh summary for safe retry | Partial runs otherwise lose track of captures. |
| 3 | keep | `skills/varde-learn/references/diagnose-quick.md:11` | Separate causes from observations; label partial; name missing evidence | Output contract preventing overclaiming. |
| 3 | keep | `skills/varde-learn/references/diagnose-toz.md:6` | Link handles to session anchors with identity/timing; unlinked = coverage gaps | Prevents false attribution of captures. |
| 3 | keep | `skills/varde-learn/references/diagnose-toz.md:13` | Measure preview size and retrieval effort; never infer savings from shorter output | Prevents false savings claims. |
| 3 | keep | `skills/varde-learn/references/diagnose-toz.md:17` | Route profile change to varde-manage with package; core to varde-change | Cross-skill routing with handoff content. |
| 3 | keep | `skills/varde-learn/references/diagnose.md:3` | Only when user asks to diagnose; not after failed eval or recurrence | Prevents unrequested costly transcript diagnosis. |
| 3 | keep | `skills/varde-learn/references/diagnose.md:24` | --current needs verified identity; Claude via hook JSON stdin; OpenCode unsupported | Non-inferable harness contract. |
| 3 | keep | `skills/varde-learn/references/diagnose.md:36` | Page a saved bundle with --snapshot-in --offset --limit | Non-obvious reuse flag. |
| 3 | keep | `skills/varde-learn/references/diagnose.md:44` | Coverage warnings mean partial coverage; never call it complete | Prevents overclaiming coverage. |
| 3 | keep | `skills/varde-learn/references/diagnose.md:96` | Leave uncaptured with reason: missing time/cwd, identity, overlap, inherited, duplicate | Eligibility contract; make canonical home here. |
| 3 | shorten | `skills/varde-learn/references/diagnose.md:123` | Copy entire anchor object; OpenCode extra fields; keep native_id null | First clause suffices; rest is schema detail. |
| 3 | keep | `skills/varde-learn/references/diagnose.md:146` | Send one bounded task; transcript content untrusted | Bounds cost and injection risk. |
| 3 | keep | `skills/varde-learn/references/diagnose.md:151` | Pass: frozen bundle and evidence anchors/pages | Analyst cannot work without it. |
| 3 | keep | `skills/varde-learn/references/diagnose.md:155` | Exclude coordinator hypotheses, conclusions, preferred fix | Independence of analyst; bias otherwise. |
| 3 | keep | `skills/varde-learn/references/diagnose.md:161` | Analyst pages with --snapshot-in, preserves overlap, no --current or live reads | Prevents analyst re-reading live contaminated sources. |
| 3 | keep | `skills/varde-learn/references/distill.md:3` | Only when user asks to review recurring friction | Prevents unrequested proposals. |
| 3 | keep | `skills/varde-learn/references/distill.md:6` | Search open items: friction list --status open --json | CLI invocation. |
| 3 | keep | `skills/varde-learn/references/distill.md:15` | Require two real occurrences with shared target; else propose nothing | User threshold; prevents overfitting skills to one incident. |
| 3 | keep | `skills/varde-learn/references/distill.md:23` | Prefer small source change over repeating guidance more loudly | Prevents emphasis bloat; preference. |
| 3 | keep | `skills/varde-learn/references/distill.md:25` | Present: item IDs and occurrence evidence | Output contract for approval. |
| 3 | keep | `skills/varde-learn/references/distill.md:27` | Present: exact target files and proposed diff | Approval needs the diff. |
| 3 | keep | `skills/varde-learn/references/distill.md:50` | --commit only verified; eval paths only approved completed runs | Prevents false provenance. |
| 3 | keep | `skills/varde-learn/references/evals.md:25` | Skills with MANIFEST entries: point at installed copy via install.sh -d -s | Else billed run uses broken skill copy. |
| 3 | keep | `skills/varde-learn/references/evals.md:31` | Budget evals x configs x runs x 2 calls; start one run; 3 before comparing | Cost preference and statistical floor. |
| 3 | keep | `skills/varde-learn/references/evals.md:36` | Compare versions with identical evals, --no-baseline; unavailable cost not zero | Prevents invalid comparisons and zero-cost claims. |
| 3 | keep | `skills/varde-learn/references/evals.md:45` | Mechanical checks in verification_script; judge sees final text, files, tool list | Schema field and grading scope. |
| 3 | keep | `skills/varde-learn/references/evals.md:48` | Accept grade only with trace evidence; unverifiable is missing, not PASS | Prevents false passes. |
| 3 | keep | `skills/varde-learn/references/evals.md:56` | 6-8 prompts labeled should_trigger; close misses; skip unrelated negatives | Format and non-default case choice. |
| 3 | keep | `skills/varde-learn/references/evals.md:59` | One run per query; Codex needs --skill-path | Non-inferable harness flag. |
| 3 | keep | `skills/varde-learn/references/reconcile.md:5` | Read full item and history with friction show | CLI invocation. |
| 3 | shorten | `skills/varde-learn/references/reconcile.md:13` | Git occurrences: verify repo_root/head_sha; compare source at commit; git log not proof | Core check; exact git commands are defaults. |
| 3 | keep | `skills/varde-learn/references/reconcile.md:19` | No Git context: use current evidence; never invent repo or SHA | Prevents fabricated provenance. |
| 3 | keep | `skills/varde-learn/references/recurrence.md:18` | Report skipped_invalid_timestamps; infer neither recurrence nor absence | Prevents false 'no recurrence' claims. |
| 3 | keep | `skills/varde-prototype/SKILL.md:24` | One topic per turn, numbered menu with recommendation | User preference; skill must stand alone. |
| 3 | keep | `skills/varde-prototype/SKILL.md:26` | Plain HTML on disk; report path first; preview never a substitute | Prevents deliverable existing only in ephemeral preview. |
| 3 | keep | `skills/varde-prototype/SKILL.md:38` | Close: final path, decisions, module to lift; plan/build -> varde-change | Close contract and handoff preference. |
| 3 | keep | `skills/varde-prototype/references/logic-track.md:3` | Edit logic.html in place; no iteration files | File contract differing from visual track. |
| 3 | keep | `skills/varde-prototype/references/logic-track.md:7` | One self-contained HTML doc, inline style, no deps or server | Format contract. |
| 3 | keep | `skills/varde-prototype/references/logic-track.md:10` | Logic as pure module: reducer/state machine/pure functions; no DOM | Enables lifting into production. |
| 3 | keep | `skills/varde-prototype/references/logic-track.md:17` | Current-state panel with labelled fields, not JSON dump | Non-default; usability for non-devs. |
| 3 | keep | `skills/varde-prototype/references/logic-track.md:21` | Guided scenario tabs; opening resets to known state | Non-default structure. |
| 3 | keep | `skills/varde-prototype/references/logic-track.md:27` | Domain language so non-developers can use it unaided | User preference. |
| 3 | keep | `skills/varde-prototype/references/logic-track.md:29` | Cover happy path, edge case, illegal action | Non-default coverage requirement. |
| 3 | keep | `skills/varde-prototype/references/visual-track.md:5` | Inspect page, neighbors, design system; preserve it | Prevents off-brand prototypes. |
| 3 | keep | `skills/varde-prototype/references/visual-track.md:16` | Given direction or refinement: write next v&lt;N>.html directly | Avoids needless variants. |
| 3 | keep | `skills/varde-prototype/references/visual-track.md:17` | Variants only when a real structural choice is unresolved | Prevents wasteful variant rounds. |
| 3 | keep | `skills/varde-prototype/references/visual-track.md:23` | variant-a.html...; shared &lt;a href> switcher; no embedding or scaling | File naming contract; embedded pages misrender. |
| 3 | keep | `skills/varde-prototype/references/visual-track.md:26` | Report paths, ask for selection; stop before v1.html | Wait gate for user choice. |
| 3 | keep | `skills/varde-prototype/references/visual-track.md:31` | Self-contained HTML; JS/runtime only if needed and user agrees | Format contract with consent condition. |
| 3 | keep | `skills/varde-prototype/references/visual-track.md:45` | Browser only when tool and target exist; never guess URL or command | Prevents fabricated URLs/commands. |
| 4 | keep | `skills/varde-agent-doc-authoring/SKILL.md:3` | Description: write or review agent documents; not user-facing docs | Trigger and sibling routing contract. |
| 4 | keep | `skills/varde-agent-doc-authoring/SKILL.md:8` | Apply review-gates.md before editing any file; carry verdict to completion | Cross-skill gate; skipping it bypasses review/approval for edits. |
| 4 | keep | `skills/varde-agent-doc-authoring/SKILL.md:15` | Route: author or revise -> references/author.md | Routing row. |
| 4 | keep | `skills/varde-agent-doc-authoring/SKILL.md:16` | Route: review -> references/review.md | Routing row. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/author.md:3` | Read target, criteria.md, specification.md | Loads the rubric; skipping it means drafting blind. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/author.md:13` | After frontmatter edits, run validate-frontmatter.py | Invalid frontmatter stops skill loading; validator catches it. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/author.md:19` | After pointer or kind changes, run skill-flow.py --write to refresh FLOW.md | FLOW.md goes stale otherwise; structural artifact. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:87` | Run scripts as uv run &lt;this-skill-dir>/scripts/&lt;name>.py; sandbox prefix UV_PYTHON_PREFERENCE | Documented sandbox failure otherwise; exact invocation. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/criteria.md:125` | Mark a reference with &lt;!-- kind: reference --> as first line | Machine-read marker for skill-flow.py. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/review.md:7` | Read criteria.md; for a skill also specification.md | Loads rubric; conditional load is correct. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/review.md:42` | Skip applying fixes when request is report-only | Write boundary; prevents unauthorized edits. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/review.md:43` | Skip applying fixes when caller restricts writes | Write boundary. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/review.md:44` | Skip applying when dispatched only to review | Prevents conflicting edits with owning agent. |
| 4 | keep | `skills/varde-agent-doc-authoring/references/specification.md:20` | End with 'Not for &lt;nearest sibling task>' when sibling overlaps | House routing convention across all Varde skills. |
| 4 | shorten | `skills/varde-agent-doc-authoring/references/specification.md:23` | One double-quoted physical-line YAML value; drop 'because loaders...' rationale | Validator enforces too, but authors need format up front. |
| 4 | keep | `skills/varde-explore/SKILL.md:3` | Description: compare options or explain code, chat or HTML | Trigger contract. |
| 4 | keep | `skills/varde-explore/SKILL.md:12` | Open question -> answer in chat (default) | Routing default. |
| 4 | keep | `skills/varde-explore/SKILL.md:13` | Direct ask for kept document -> explain.md | Routing row. |
| 4 | keep | `skills/varde-explore/references/explain.md:3` | One self-contained HTML file, inline CSS, no external assets | Output format contract. |
| 4 | keep | `skills/varde-explore/references/explain.md:26` | Write to user path or &lt;working>/explanations/&lt;date>-&lt;slug>.html; report exact path | Path contract. |
| 4 | keep | `skills/varde-knowledge/SKILL.md:3` | Description: record/find knowledge, wrap up, handoffs | Trigger contract. |
| 4 | keep | `skills/varde-knowledge/SKILL.md:12` | Route: find or record knowledge -> note.md | Routing row. |
| 4 | keep | `skills/varde-knowledge/SKILL.md:13` | Route: wrap up -> reflect.md | Routing row. |
| 4 | keep | `skills/varde-knowledge/SKILL.md:14` | Route: write handoff -> handoff-write.md | Routing row. |
| 4 | keep | `skills/varde-knowledge/SKILL.md:15` | Route: resume -> handoff-resume.md | Routing row. |
| 4 | keep | `skills/varde-knowledge/SKILL.md:16` | Route: check note vs code -> reconcile.md | Routing row. |
| 4 | keep | `skills/varde-knowledge/SKILL.md:18` | Resolve &lt;working>/&lt;knowledge> via varde-workflow paths --json; retry, ask, never guess | Path contract for every route. |
| 4 | keep | `skills/varde-knowledge/references/handoff-resume.md:5` | List open handoffs, frontmatter only, newest first; prefer cwd, branch, keywords | Path and selection contract. |
| 4 | keep | `skills/varde-knowledge/references/handoff-resume.md:17` | On confirmation set status: resumed | State transition. |
| 4 | keep | `skills/varde-knowledge/references/handoff-resume.md:27` | content_hashes: recompute via handoff-snapshot.py; modified/unchanged/unknown | Must match writer's algorithm. |
| 4 | keep | `skills/varde-knowledge/references/handoff-snapshot.md:6` | Run python3 scripts/handoff-snapshot.py -- &lt;target>...; record entries as printed | Invocation contract; path is cwd-relative. |
| 4 | keep | `skills/varde-knowledge/references/handoff-write.md:5` | Record cwd, repo_root, branch, head_sha, dirty; exact none values outside Git | Resume depends on these fields. |
| 4 | keep | `skills/varde-knowledge/references/handoff-write.md:9` | Redact keys, tokens, passwords, connection strings, PII | Secrets safety boundary. |
| 4 | keep | `skills/varde-knowledge/references/handoff-write.md:12` | Links as {target, kind, integrity} | Schema resume reads. |
| 4 | keep | `skills/varde-knowledge/references/handoff-write.md:29` | Save to &lt;working>/handoffs/&lt;date>-&lt;slug>/handoff.md; report ID and path | Path contract resume globs. |
| 4 | keep | `skills/varde-knowledge/references/handoff-write.md:32` | type: handoff, status: open | Resume filters on status. |
| 4 | keep | `skills/varde-knowledge/references/handoff-write.md:35` | cwd and keywords | Resume match keys. |
| 4 | keep | `skills/varde-knowledge/references/handoff-write.md:36` | repo_root, branch, head_sha, dirty from step 1 | Resume drift check keys. |
| 4 | keep | `skills/varde-knowledge/references/handoff-write.md:37` | links from step 3 | Resume link labeling input. |
| 4 | keep | `skills/varde-knowledge/references/note.md:17` | Path &lt;knowledge>/&lt;type>/&lt;slug>.md; type top-level, never under domain | Path contract. |
| 4 | keep | `skills/varde-knowledge/references/note.md:19` | New types definition/decision/pattern/reference; leave other producers' folders | Type vocabulary; protects generated specs. |
| 4 | keep | `skills/varde-knowledge/references/note.md:23` | Reserved index.md/log.md; regenerate maps with concept map, never by hand | Generated artifact contract. |
| 4 | keep | `skills/varde-knowledge/references/note.md:31` | Never store session narrative, output, secrets, unverified guesses | Knowledge is committed; secrets leak outward. |
| 4 | keep | `skills/varde-knowledge/references/note.md:38` | generated: {by, at}; human:&lt;id> vs &lt;harness>/&lt;model-id> | Provenance contract not inferable. |
| 4 | keep | `skills/varde-knowledge/references/note.md:78` | Retire with status: deprecated, not delete; draft/stable/deprecated | Deletion breaks links; state vocabulary. |
| 4 | keep | `skills/varde-knowledge/references/note.md:85` | Link with bundle-absolute paths under ## Related | Link format contract. |
| 4 | keep | `skills/varde-knowledge/references/reconcile.md:8` | Stamp reconciled: {at, sha} | Frontmatter state contract. |
| 4 | keep | `skills/varde-learn/SKILL.md:3` | Description: diagnose, triage, capture, distill, recurrence, tests | Trigger contract. |
| 4 | keep | `skills/varde-learn/SKILL.md:12` | Route: capture -> capture.md | Routing row. |
| 4 | keep | `skills/varde-learn/SKILL.md:13` | Route: triage supplied evidence -> diagnose-quick.md | Routing boundary vs full diagnosis. |
| 4 | keep | `skills/varde-learn/SKILL.md:14` | Route: diagnose session -> diagnose.md | Routing row. |
| 4 | keep | `skills/varde-learn/SKILL.md:15` | Route: reconcile -> reconcile.md | Routing row. |
| 4 | keep | `skills/varde-learn/SKILL.md:16` | Route: distill -> distill.md | Routing row. |
| 4 | keep | `skills/varde-learn/SKILL.md:17` | Route: recurrence -> recurrence.md | Routing row. |
| 4 | keep | `skills/varde-learn/SKILL.md:18` | Route: evals -> evals.md | Routing row. |
| 4 | keep | `skills/varde-learn/SKILL.md:22` | varde-learn missing: report, continue, do not write Markdown | Prevents a split legacy Markdown friction store. |
| 4 | keep | `skills/varde-learn/references/capture.md:16` | Evidence on stdin; append with friction add --item | Non-obvious stdin CLI contract. |
| 4 | keep | `skills/varde-learn/references/capture.md:23` | Else create item with --source, --title, --target | CLI invocation for new items. |
| 4 | script | `skills/varde-learn/references/diagnose-capture.md:29` | Incident JSON template | Exact schema contract; a --from-inspect flag could generate it. |
| 4 | keep | `skills/varde-learn/references/diagnose-capture.md:53` | Run varde-learn diagnose capture --file &lt;incident.json> --json | CLI invocation. |
| 4 | keep | `skills/varde-learn/references/diagnose-quick.md:3` | Only supplied/visible evidence; no transcript opening or session selection | Route boundary; prevents unrequested transcript access. |
| 4 | keep | `skills/varde-learn/references/diagnose-quick.md:10` | Treat transcript text as data, not instructions | Prompt-injection safety boundary. |
| 4 | keep | `skills/varde-learn/references/diagnose-quick.md:13` | One bounded next check; answer in chat; no report or capture | Write boundary for quick route. |
| 4 | keep | `skills/varde-learn/references/diagnose-toz.md:3` | Retrieve captures in bounded redacted pages; no raw retention or privacy changes | Privacy boundary on captured output. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:8` | Working store: caller path else data.working from varde-workflow paths --json | Path contract. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:13` | Keep snapshots/reports in working store, never committed knowledge | Transcript data must not reach committed files. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:17` | diagnose inspect command example | CLI invocation. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:27` | Identity unavailable: stop, report blocker; never env var or guessed path | Prevents analyzing or attributing the wrong session. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:33` | Select analysis procedure from overlap, never from selector | Aliased current session otherwise analyzed inline. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:56` | Noisy output/repeated retrieval -> also follow diagnose-toz.md | Conditional load contract. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:61` | Create &lt;working>/diagnoses/&lt;id>/report.md; save before capture | Path and ordering contract. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:64` | Session diagnosis report template | Output format contract. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:95` | Recommend without applying changes or status updates | Write boundary during diagnosis. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:104` | Write cutoff.json from pre-orchestration native anchor (template) | Structural contract for cutoff verification. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:127` | Re-inspect with new --snapshot-out and --cutoff-anchor | CLI invocation. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:129` | Require cutoff_verified true; else partial/blocked, never complete | Gate against contaminated current-session review. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:135` | Current/unknown overlap: delegate one independent analyst natively | Core contract: self-analysis of own session is contaminated. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:142` | No native delegation: stop; no self-analysis or subprocess client | Prevents transcript leaving via subprocess clients. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:156` | Exclude unbounded transcript, database, auth data, private config | Safety boundary on data handed to subagent. |
| 4 | keep | `skills/varde-learn/references/diagnose.md:170` | After report, load diagnose-capture.md only for eligible incidents; report-only stops | Conditional load and exit. |
| 4 | keep | `skills/varde-learn/references/distill.md:34` | Apply through varde-change build micro-change; doc-authoring review of skill diff first | Cross-skill routing required by user workflow. |
| 4 | keep | `skills/varde-learn/references/distill.md:39` | Record adoption with adopt record command | CLI state transition. |
| 4 | keep | `skills/varde-learn/references/evals.md:14` | evals/evals.json with prompts, expected_output, files, assertions | Schema contract read by CLI. |
| 4 | keep | `skills/varde-learn/references/evals.md:24` | Run varde-learn eval output &lt;skill-dir>; --help lists options | CLI invocation. |
| 4 | keep | `skills/varde-learn/references/evals.md:34` | Git-history runs in disposable standalone clone, never linked worktree | Linked worktree shares refs; eval can mutate real repo. |
| 4 | keep | `skills/varde-learn/references/evals.md:63` | eval trigger command | CLI invocation. |
| 4 | keep | `skills/varde-learn/references/reconcile.md:22` | Explicit request authorizes unambiguous status; ask when missing, ambiguous, destructive | State-transition authorization boundary. |
| 4 | keep | `skills/varde-learn/references/reconcile.md:26` | Record reason via friction set-status | CLI state transition. |
| 4 | keep | `skills/varde-learn/references/reconcile.md:32` | Do not edit exported Markdown or SQLite directly | Direct edits corrupt the store. |
| 4 | keep | `skills/varde-learn/references/recurrence.md:7` | adopt recurrence --json --limit 100; page by next_offset | CLI invocation. |
| 4 | keep | `skills/varde-learn/references/recurrence.md:21` | Offer to investigate before proposing; never revert automatically | Blocks destructive automatic reverts. |
| 4 | keep | `skills/varde-prototype/SKILL.md:3` | Description: shape/prototype frontend or clickable walkthrough | Trigger contract. |
| 4 | keep | `skills/varde-prototype/SKILL.md:8` | Prototype files need no review gate; production edits through varde-change | Cross-skill gate boundary. |
| 4 | keep | `skills/varde-prototype/SKILL.md:15` | Visual track -> visual-track.md | Routing row. |
| 4 | keep | `skills/varde-prototype/SKILL.md:16` | Logic track -> logic-track.md | Routing row. |
| 4 | keep | `skills/varde-prototype/SKILL.md:32` | Storage &lt;working>/prototypes/&lt;slug>/ or plan-owned path; ask only if exists | Path contract. |
| 4 | keep | `skills/varde-prototype/SKILL.md:44` | Resolve &lt;working> via varde-workflow paths; never guess | Storage path depends on it. |
| 4 | keep | `skills/varde-prototype/references/visual-track.md:39` | Saved revisions unchanged; each refinement writes next v&lt;N>.html | File versioning contract. |
| 5 | keep | `skills/varde-learn/references/distill.md:30` | Ask approval of exact source scope (incl installed copies) and billed evals with cost | Consent for edits and spending money. |
| 5 | keep | `skills/varde-learn/references/evals.md:8` | Run no eval session until user approves run and cost | Billed-cost consent boundary. |

## 2. Correctness defects

1. **Write route cannot produce the hashes resume checks.** `skills/varde-knowledge/references/handoff-write.md:22` tells the agent to add `content_hashes` with `integrity: snapshot`, but never points to `references/handoff-snapshot.md` or `scripts/handoff-snapshot.py`. Resume (`handoff-resume.md:27`) recomputes with that script, so hand-built hashes (different key shape or hash kind) will label links `modified` or `unknown`. Fix: add one line to step 3 naming the script.
2. **Script path is cwd-relative.** `skills/varde-knowledge/references/handoff-snapshot.md:6` runs `python3 scripts/handoff-snapshot.py`, which only resolves when cwd is the skill directory. The authoring rule (`criteria.md:87`) prescribes a skill-dir-rooted invocation.
3. **Contradictory gotcha placement.** `criteria.md:151` says end SKILL.md with a `## Gotchas` section; `criteria.md:159` says "keep gotchas inline". Pick one meaning (for example, "keep a correction next to the step it fixes; put only always-needed ones in Gotchas").
4. **Mis-structured list.** `criteria.md:104-106`: under the lead-in "Split references only:", the second bullet is a layout rule, not a split condition, and the first bullet is one over-long line. Also no blank line before the list.
5. **Unused boilerplate.** `varde-explore/SKILL.md:23` and `varde-prototype/SKILL.md:44` resolve `<knowledge>`, which neither skill uses, and say "Outside the repo, use plain file ops instead of git" with no git write step to apply it to.
6. **Own formatting rule broken.** `skills/varde-explore/references/explain.md:29-30`: no blank line between the last list item and `## HTML output sections` (violates `criteria.md:78-80`).
7. **Ambiguous "do not write Markdown".** `skills/varde-learn/SKILL.md:22` forbids Markdown when the CLI is missing, but `diagnose.md:61` writes `report.md`. It should say "do not record friction in Markdown".
8. **Dead spec rows.** `specification.md:9` and `:26` document `allowed-tools`, which no Varde SKILL.md uses. `:26` also says its own rule is unenforced.
9. **Order ambiguity.** `skills/varde-learn/references/distill.md:34-36` says "have varde-agent-doc-authoring review any skill diff first". It is unclear whether that review happens before the approval in step 5 or inside `varde-change build`. Same concern for the user's global rule, which requires a doc-authoring review after any skill edit.

## 3. Structural observations

1. **`varde-learn/references/diagnose-capture.md` (385 words) mostly restates CLI-owned behavior.** CLI-owned parts: output descriptions (L54-60), witness identity (L68-72), strict-JSON limits (L21-22), "never invent" (L11-12), and prose that duplicates the template's field mapping (L22-27). Cutting them saves about 200 words. A `varde-learn diagnose capture --from-inspect <bundle> --record <i> --kind <k>` flag would also replace the 70-word template and the copy step, which is the most error-prone manual work in the route.
2. **`diagnose.md` (888 words) always loads the current/unknown-overlap branch** (L100-166, about 400 words). A `not_current` diagnosis skips that branch. By the skill's own rule (a conditional path many runs skip, at about 400 words), it could split into `diagnose-current.md`. The saving (about 400 words per `not_current` run) depends on how often targets are past sessions. Inline redundancies (L29-34, L43, L47-49, L138-144, L171, L93-94) add about 150 more cuttable words.
3. **Paging boilerplate appears 5 times** (`capture.md:12`, `distill.md:12`, `reconcile.md:11`, `recurrence.md:13`, `diagnose.md:36`). One SKILL.md gotcha ("page every list/show/recurrence result until `meta.truncated` is false") saves about 80 words.
4. **The path/sandbox-retry boilerplate appears in 5 files** (`varde-learn/SKILL.md:22`, `diagnose.md:10`, and the gotchas of knowledge, explore, and prototype). Repo AGENTS.md already owns the retry posture. Keep only the path command and "never guess"; drop the unused `<knowledge>` and git clauses. Saves about 60 words.
5. **`criteria.md` (1,168 words) loads on every author and review run**, and about 150 of its words describe what `check-length.py` and `skill-flow.py` compute: L84-86, the thresholds table, L98, L67-69, and the L78-80 rationale. Put the thresholds and fix hints into the scripts' messages, and keep only "run it; fix defects; justify warns". Merge candidates inside the file (L16/L51, L29/L50, L43, L61, L63/L71, L149/L110, L163) save about 80 more words.
6. **`specification.md` (208 words) loads unconditionally in `author.md:3`.** It matters only for SKILL.md frontmatter and descriptions, so load it only for SKILL.md edits (saves 208 words per AGENTS.md/CLAUDE.md edit). Rows the validator owns (L7, L9, L11, L12, L26) and the duplicate validation note (L30) save about 75 words.
7. **The `varde-learn` evals route could script the changed-skill listing** (`evals.md:39-41`) as a CLI flag (for example, `varde-learn eval changed --since <ref>`).
8. **Candidates to script or drop:** the `handoff-resume.md:32-35` legacy-link branch (about 55 words) could become a `handoff-snapshot.py --legacy` mode or be dropped once no legacy handoffs remain in the working store. Check `<working>/handoffs/` first. `A/SKILL.md:25` (`</content>` check) belongs in `check-length.py`.
9. **Prototype and explore duplicate the SKILL-level question and production rules** inside their references (`logic-track.md:31`, `visual-track.md:34`, `:40`) and restate description "Not for" lines (`varde-prototype/SKILL.md:19`). About 60 words.

Estimated total savings: about 1,250 words of the 8,203 in scope (15%). Conditional loads save another 208 to 400 words per affected run.

## 4. Totals

| Score | Units |
|---|---|
| 0 | 6 |
| 1 | 54 |
| 2 | 141 |
| 3 | 132 |
| 4 | 98 |
| 5 | 2 |

Total units: 433. Words in score 0-1 units: about 784 (estimated per unit).
