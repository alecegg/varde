# Reassess failed attempts

Load only at the stopping point specified by dispatch or debug posture.

Report a brief reassessment in chat. For a task, its owner also records it in
`#### Progress`; parallel workers report it to the orchestrator instead:

1. Summarize the failed attempts and their observed results.
2. Assess whether the evidence supports a wrong hypothesis, inadequate
   reproduction, environment/test limitation, or design problem. State
   uncertainty when the evidence cannot distinguish them; repeated failures
   alone do not establish that the architecture is wrong.
3. State what evidence, approach, access, or design must change before another
   attempt. A retry must identify what changed rather than repeat the failed
   approach blindly.

Keep the caller's retry budget and blocked-task controls. Escalate to the human
only for unresolved choices or scope changes requiring their input. A materially
revised plan returns to the existing independent pre-edit review gate; this
reassessment adds no routine review cycle.
