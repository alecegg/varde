# Pipeline queue (orchestrator-only writer; top is next)
Format: <plan>:<task> | fix:<yes|no> | worktree:<abs path or ->
Session slots: builder = pipeline-builder, reviewer = pipeline-reviewer. Orchestrator = this notes dir owner.
Order rule: respect plan depends_on; same-file items stay ordered. Native-cutover depends on liveness + native-workspaces (running, unmerged at 2026-10-25): c1 touches no store.py so it starts now; c3 (store.py) waits for liveness merge.

native-cutover:c1 | fix:no (fix1 2c00063e in review) | worktree:/Users/alec/.paseo/worktrees/05wfodp6/goofy-armadillo   (SPEC-001 guard.py run_model must route via role.harness plugin; see c1-review.md)
pipeline:p2 | fix:no | worktree:/Users/alec/.paseo/worktrees/05wfodp6/zealous-deer   (3b005098 in review)   (luna; queue check CLI + signals; right after c1)
pipeline:p1-agents | fix:no | worktree:/Users/alec/.paseo/worktrees/05wfodp6/creepy-panther (building)   (capabilities.json + generated agent files only, no skill prose)
pipeline:p1-skills | fix:no | worktree:-   (needs agent-doc-authoring review + user sign-off via main before merge)
native-cutover:c3 | fix:no | worktree:-   (blocked: liveness merge, c1)
native-cutover:c4 | fix:no | worktree:-   (c3)
native-cutover:c5 | fix:no | worktree:-   (c3)
node-host:h1 | fix:no | worktree:-   (sonnet)
claude-sdk-adapter:s1,s2 | fix:no | worktree:-  (sonnet)
native-cutover:c2 | fix:no | worktree:-  (after adapter merge)
chat-threads | identity-registry:p1,p2 | manager-delegation | settings-home | pi-durable-engine (after spike) | paseo-removal (after gate + user approval)

## Status 2026-10-25
- native-cutover c1: reviewed (pass after fix1), merged to branch worktree/2026-10-25-native-cutover (worktree .paseo/worktrees/05wfodp6/plan-native-cutover).
- pipeline p2: reviewed pass, merged to branch worktree/2026-10-25-pipeline-orchestration (plan-pipeline worktree).
- pipeline p1-agents: 0d6e64cb in review (creepy-panther).
- node-host h1: Sonnet builder e76bd5c9 building in angry-fish; node-host reviewed_commit stamped affe32b8.
- Luna builder e3fda9ae idle: c3/c4/c5 blocked on liveness merge; next candidate p3 later / manager chain.

## Status 2026-10-25 21:20 (supersedes above)
Concluded: runner-liveness-recovery, identity-registry, runner-node-host. Rule (main): every plan queue ends with a CONCLUDE item (reviewer diff check -> re-stamp reviewed_commit if merged head differs -> merge -> deploy if needed -> varde plan conclude with plan-dir review.md head == merged head).
Plan branches: native-cutover (c1,c3,c4,c5; c2 waits adapter; conclude waits user dogfood gate), chat-threads (t1,t2,t3; t4,t8-fix in progress; t5-t7,t9; then CONCLUDE), pipeline (p2,p1-agents; p1-skills in doc review; p3,p5 later; CONCLUDE), claude-sdk-adapter (s1; s2 in review; s3-s5; CONCLUDE).
Slot rule: check get_agent_status for builder and reviewer every ~10 min; "queued" prompts can be dropped, so send explicit DO NOW tasks.
