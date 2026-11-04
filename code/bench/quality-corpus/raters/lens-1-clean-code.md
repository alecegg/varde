---
lens: clean-code
version: 2
---

# Rater instructions: lens 1, Clean Code

You judge two versions, A and B, of the same behaviour in one language, **only through the lens below**. Do not bring in principles from other schools of design. If the lens gives no answer to a question, answer `na`.

## Lens

1. Functions should be small; then smaller.
2. A function should do one thing: a descriptive-named function should be extractable from it, and extraction must add meaning. A wrapper whose name merely restates its body does not satisfy this.
3. One level of abstraction per function; code reads top-down, each function followed by those one level lower.
4. Descriptive names let a reader understand a caller without opening the callee.
5. Few arguments: zero is ideal, one or two normal, three or more needs strong justification.
6. Avoid duplication and avoid entanglement (functions that cannot be understood without reading each other).
7. When in doubt, prefer decomposition, but only decomposition that adds meaning.

## Rubric (answer A, B, tie or na)

- Q1 Size: which version's functions are individually easier to take in at a glance?
- Q2 One thing: in which version does each function do one nameable thing, with extractions that add meaning?
- Q3 Abstraction level: in which version does each function stay at one level of abstraction?
- Q4 Names: in which version do names let a reader skip the callee?
- Q5 Arguments: which version has fewer and simpler arguments per function?
- Q6 Duplication: which version has less repeated logic?
- Q7 Top-down reading: which version reads better from the entry point downward?
- Q8 Entanglement: in which version can functions be understood without reading the functions they call or are called by?

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
