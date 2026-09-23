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
- **Re-scan for gaps before ending.** An empty queue only resolves the known
  questions. Before closing the round, scan for placeholders, conflicting
  decisions, and unclear scope.
- **Detect context saturation.** If you re-ask resolved questions, lose earlier
  decisions, or ask vaguer questions, context quality is declining. Round count
  alone is not evidence. Say so directly, suggest `varde-knowledge reflect` to
  compact progress into a resumable handoff, then continue in a fresh session.

## Question format

Write the question inline in your message text, using a numbered menu. Keep the
question and answer together in one record; a harness question tool renders that
text outside.

```
<Question>

  1. <Option A>
  2. <Option B>
  3. Other — describe what you want

Recommendation: <n> (<label>) — <one-sentence reason>.
```

## Resolve questions in the document

Apply these rules in chat. If a workflow also lets the user resolve open items
by editing a document, as `references/plan-grow-doc.md` does, treat a doc edit
that answers or corrects something as a resolved decision, just like a chat
reply.
