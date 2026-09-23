# Ask the user questions

Shared rules for skills that ask the user questions.

## Core rules

- **One question per turn:** End your turn and wait before asking the next.
- **Recommend an option:** State which option you recommend and why in one
  sentence. Use severity, confidence, blast radius, or a relevant context clue.
- **Wait for an explicit answer:** Do not treat silence or surrounding context
  as the user's decision.
- **Name unresolved dependencies:** If an answer depends on an open question,
  defer it and say what is missing.
- **Re-scan for gaps before ending:** An empty queue means you resolved the
  known items, not that you found every gap. Check for placeholders, conflicting
  decisions, and unclear scope before closing the round.
- **Watch for context saturation:** Re-asking a resolved question, losing track
  of earlier decisions, or asking vaguer questions signals declining context
  quality. Round count alone does not. Say so directly, suggest
  `varde-knowledge reflect` to compact progress into a resumable handoff, and
  continue in a fresh session.

## Question format

Ask inline in your message text, using a numbered menu. Keep the question and
answer together in one readable record. The harness question tool renders this
text separately.

```
<Question>

  1. <Option A>
  2. <Option B>
  3. Other — describe what you want

Recommendation: <n> (<label>) — <one-sentence reason>.
```
