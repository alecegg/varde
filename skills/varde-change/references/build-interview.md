# Ask the user questions

Shared rules for skills that ask the user questions.

## Core rules

- **One question per turn:** End your turn and wait before asking the next.
- **Every option carries a recommendation.** Say which you recommend and why in
  one sentence — severity, confidence, blast radius, or the context clue that
  points to it.
- **Wait for an explicit answer.** Silence and surrounding context leave the
  decision open.
- **Name unresolved dependencies.** When an answer depends on an open question,
  defer it and say what is missing.
- **Check for gaps before ending.** An empty queue means all known questions
  are resolved. It does not prove that nothing was missed. Check for
  placeholders, conflicting decisions, and unclear scope before closing.
- **Watch for context saturation.** Re-asking something already resolved, losing
  track of earlier decisions, or your own questions getting vaguer all mean the
  context window is degrading question quality — round count alone does not. Say
  so directly and suggest `varde-knowledge reflect` to compact progress into a
  resumable handoff, then continue in a fresh session.

## Question format

Ask inline, in your message text, using a numbered menu. Your own text keeps the
question and its answer together in one readable record, which a harness question
tool renders outside.

```
<Question>

  1. <Option A>
  2. <Option B>
  3. Other — describe what you want

Recommendation: <n> (<label>) — <one-sentence reason>.
```
