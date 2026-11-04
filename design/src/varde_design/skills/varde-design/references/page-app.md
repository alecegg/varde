# Operate: app screen, list, dashboard, tool

Use when the user works through the page repeatedly. Density and speed beat atmosphere.

## States (every data region)
- Empty: say what is empty and give the next action as a button ("No invoices yet. Create invoice").
- Loading: skeleton rows at the final row height so nothing jumps; no spinner alone.
- Error: what failed, what to do, a retry control, kept inline in the region, not a blocking page.
- Long content: truncate to one line with a title attribute, wrap multi-line cells, keep action columns fixed.
- Busy action: disable the control, show progress text, then a result message.
- The primary action is the only filled button on screen.
- Status is never shown by colour alone.

## Checks
Gate: R1, R2, R3, R6, S6. Advisory: S4, S5, R5.
Judgement (not checked): R7, S7, S9, S10.
