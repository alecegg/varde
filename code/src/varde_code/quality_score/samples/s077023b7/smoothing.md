# Style decisions

- **Calculation structure: `judge-inline.ts` wins.** The invoice arithmetic reads in domain order in one function. The small rounding and validation predicates remain shared helpers, while extraction into a separate read/build pipeline would add indirection without reuse.
- **Names: `judge-extract.ts` wins.** Names such as `roundMoney`, `isPlan`, `planDetails`, and `appliedCredits` are concise while still identifying their purpose. The longer names in `judge-names.ts` add length without making the calculations clearer.
- **Comments: `judge-inline.ts` wins.** The operations and field names make the flow clear without line-by-line narration. The comments in `judge-defensive.ts` repeat what the code already expresses.
- **Abstraction level: `judge-inline.ts` wins.** A plain catalog and functions fit this small module. The classes and interfaces in `judge-classes.ts` add objects and state without an independent responsibility that needs them.
- **Report formatting: `judge-extract.ts` wins.** A shared `formatLine` and `formatMoney` keep labels and currency formatting consistent; rendering the ordered rows directly with `join` stays easy to scan.
- **Validation factoring: `judge-extract.ts` wins.** Reusable predicates make the plan, text, and unit checks easier to read while keeping the amount and tax range checks explicit and close to the inputs.
