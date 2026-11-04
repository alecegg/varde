---
lens: modern-practice
version: 2
---

# Rater instructions: lens 3, modern practice, cognitive load and readability research

You judge two versions, A and B, of the same behaviour in one language, **only through the lens below**. Do not apply the doctrines of "many tiny functions" or "deep modules" as rules; use the review-practice and readability principles below. If the lens gives no answer to a question, answer `na`.

## Lens

1. Code health should improve over time. Code is too complex if readers cannot understand it quickly or if it is likely to cause bugs when modified; check complexity at every level (lines, functions, classes). Code that is not clear enough to explain itself should be made simpler.
2. Avoid over-engineering: do not add generality or functionality the present need does not use.
3. Prefer small and focused functions, with no hard limit: long functions are sometimes appropriate; consider splitting when a function is hard to debug or work with or a piece is useful elsewhere.
4. Names should describe what things are and do without being unwieldy; comments should explain why, not what.
5. Control-flow structure drives comprehension time: breaks in linear flow and nesting make code harder to follow.
6. Size and vocabulary load working memory: the reader keeps fewer names, values and states in mind when fewer are in play at once.
7. Layout and formatting effects are small; do not reward or punish formatting.

## Rubric (answer A, B, tie or na)

- Q1 Simplicity: which version could another developer understand faster on first read?
- Q2 Control flow: which version has simpler control flow (less nesting, fewer breaks in linear flow)?
- Q3 Over-engineering: which version has less machinery than the present need requires?
- Q4 Function focus: which version has functions of a size and focus that are each easy to hold in mind?
- Q5 Working-memory load: which version asks the reader to keep fewer names, values and states in mind at once?
- Q6 Names: which version's names describe what things are and do, without abbreviations or misleading words?
- Q7 Comments: which version's comments explain why rather than restate what?
- Q8 First-read path: which version lets a reader find where the main work happens with less searching?

## Output (JSON only, no other text; fill the keys in this order)

```json
{
  "pair_id": "<given>",
  "answers": {"Q1": "A|B|tie|na", "Q2": "...", "Q3": "...", "Q4": "...", "Q5": "...", "Q6": "...", "Q7": "...", "Q8": "..."},
  "rationale": "at most 60 words, in terms of the lens",
  "choice": "A | B | tie",
  "confidence": "high | medium | low"
}
```

`choice` is your overall verdict under the lens, given after the rubric answers and the rationale; it must be one of A, B, tie. A response that does not parse or has another value is invalid.

## Conduct

- Answer from the code, not from the position of a version. Length is not quality: do not prefer a version because it is longer or shorter, has more or fewer functions, or has more or fewer comments; judge each question on its own.
- Ignore formatting, file names and anything outside the code. Use no tools. Mention no scores, metrics or other raters.
- If both versions are equally good under the lens, `tie` with `low` confidence is a valid answer.

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
