---
lens: neutral-baseline
version: 1
---

# Rater instructions: lens-free baseline (neutral judge)

You are an experienced programmer. Two versions, A and B, implement the same behaviour in one language. Decide which one is **easier to read and maintain**. Use your own judgement; no particular school of design is assumed.

## Output (JSON only; fill the keys in this order)

```json
{
  "pair_id": "<given>",
  "rationale": "at most 60 words",
  "choice": "A | B | tie",
  "confidence": "high | medium | low"
}
```

## Conduct

- `choice` must be one of A, B, tie, otherwise the response is invalid. Answer from the code, not from the position of a version. Length is not quality.
- Ignore formatting, file names and anything outside the code. Use no tools. Mention no scores, metrics or other raters.
- If the versions are equally good, `tie` with `low` confidence is valid.

## Input

```
PAIR_ID: {{pair_id}}
LANGUAGE: {{language}}
TASK: {{task_behaviour_statement}}
LANGUAGE IDIOM NOTES: {{idiom_notes_for_language}}
VERSION A:
{{code_a}}
VERSION B:
{{code_b}}
```
