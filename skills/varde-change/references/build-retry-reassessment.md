# Reassess failed attempts

Report a brief reassessment in chat. For a task, its owner also records it in
`#### Progress`; parallel workers report it to the orchestrator instead.

1. Summarize the failed attempts and their observed results.
2. Assess which the evidence supports, stating uncertainty when it cannot
   distinguish them; repeated failures alone do not prove the architecture
   wrong:
   - a wrong hypothesis
   - inadequate reproduction
   - an environment or test limitation
   - a design problem
3. State what evidence, approach, access, or design must change before another
   attempt; a retry names what changed.

Rules:

- Escalate to the human only for unresolved choices or scope changes needing
  their input.
