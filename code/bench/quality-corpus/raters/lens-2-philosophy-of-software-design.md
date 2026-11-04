---
lens: aposd
version: 2
---

# Rater instructions: lens 2, A Philosophy of Software Design

You judge two versions, A and B, of the same behaviour in one language, **only through the lens below**. Do not bring in principles from other schools of design. If the lens gives no answer to a question, answer `na`.

## Lens

1. Complexity is the enemy. Its symptoms are change amplification (a simple change needs edits in many places), cognitive load (a developer must know many things to finish a task) and unknown unknowns.
2. Modules (including functions) should be deep: substantial functionality behind a simple interface. Shallow pieces, whose callers must understand almost everything inside, add interface cost without hiding anything.
3. Information hiding is the main technique for depth.
4. Splitting can go too far: as pieces get smaller there is less benefit to further subdivision. Watch for pass-through methods and for pieces that are only understandable together; combine entangled pieces.
5. Split when the pieces are general-purpose or the interface gets simpler; keep together what is better together.
6. Pull complexity downward; define errors out of existence where possible. A function that is merely long and deeply nested is **not** deep and not simple.
7. Comments should state what the code cannot say (intent, rationale).

## Rubric (answer A, B, tie or na)

- Q1 Interface versus work: in which version do functions do more useful work relative to the knowledge a caller needs?
- Q2 Shallow pieces: which version has fewer shallow pieces (tiny functions whose callers must still understand the whole body)?
- Q3 Entanglement: which version has fewer functions that can only be understood by reading others?
- Q4 Information hiding: in which version does a caller need to know fewer internal decisions of the callee?
- Q5 Cognitive load: for a typical change to the behaviour described in TASK, in which version must a reader hold fewer things in mind and open fewer places?
- Q6 Change amplification: for that change, in which version would fewer places need editing?
- Q7 Complexity location: in which version is complexity concentrated where it is rarely seen rather than spread across call sites, without becoming one long nested block?
- Q8 Comments and naming: in which version does the text explain what the code cannot?

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
