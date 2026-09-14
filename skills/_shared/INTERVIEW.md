# Interview protocol

Shared reference for all skills in this repo that conduct structured questioning.

---

## Core rules (all harnesses)

- **One question per turn.** End your turn and wait before asking the next.
- **Every option must include a recommendation.** State which you recommend and
  why in one sentence — severity, confidence, blast radius, or the context clue
  that points to it.
- **Never treat silence or context as assent.** A recommendation without a
  response is not a resolved decision. Wait explicitly.
- **Fog discipline.** If a question's answer depends on something unresolved,
  defer it and name it as fog.
- **Empty queue is not the exit condition.** Running out of queued questions
  means the *known* frontier is resolved, not that nothing was missed. Before
  treating the round as closed, actively re-scan for gaps (placeholders,
  contradictions between decisions, unstated scope, ambiguity) rather than
  exiting because there's nothing left to ask.
- **Watch for context saturation, not just round count.** A session with
  many rounds isn't automatically a problem — but re-asking something
  already resolved, losing track of earlier decisions, or noticing your own
  questions and recommendations getting vaguer are signs of the "dumb zone":
  a full context window degrading question quality rather than sharpening
  it. When you notice this, don't push through on the assumption more rounds
  will fix it. Tell the user directly and suggest `/varde-handoff` to
  compact progress into a resumable doc, then continue the remaining
  questions in a fresh session.

---

## Question format (all harnesses)

Do not use a harness's native question-prompt tool (e.g. Claude Code's
`AskUserQuestion`), even where one is available — it renders outside the
continuous transcript, so the question and the answer don't stay together in
one readable record. Always ask inline, in your message text, using a
numbered menu:

```
<Question>

  1. <Option A>
  2. <Option B>
  3. Other — describe what you want

Recommendation: <n> (<label>) — <one-sentence reason>.
```
