# Form and flow: sign-up, settings, checkout, wizard

Use when the user supplies data to finish a task. Completion and trust beat polish.

## States
- Empty: fields blank with example format, submit enabled unless the missing input is obvious.
- Validation: check on blur or submit, not per keystroke. Error text names the fix ("Use at least 8 characters"), sits under the field, with a summary at the top for long forms.
- Busy: submit shows progress and is disabled; keep entered values.
- Success: say what happened and what comes next; do not clear to a blank form.
- Failure: server errors keep all input and offer retry. Destructive steps ask for confirmation naming the object.
- A form that posts nowhere must say so on the page (prototype notice); never fake a success.
- Labels stay visible above fields; targets are 44 px high.

## Checks
Gate: R1, R2, R3, R6. Advisory: S4, S5.
Judgement (not checked): R7 (focus ring), S8 (placeholder copy).
