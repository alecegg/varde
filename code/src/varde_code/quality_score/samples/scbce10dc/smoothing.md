# Smoothing decisions

- **Granularity: `judge-extract` wins.** Its inventory parsing, order-line pricing, totals, and formatting helpers keep each operation understandable while avoiding the many one-use wrapper methods and intertwined validation/calculation in `judge-names` and `judge-inline`.
- **Names: `judge-names` wins in moderation.** Descriptive terms such as `subtotal`, `afterDiscount`, `orderSubtotal`, and `validInventoryFields` make the calculations clear. The longer names such as `splitIntoRows` and `calculateOrderTotals` add little, so the smoothed version uses shorter names where context is clear.
- **Comments: `judge-inline` wins.** The code is straightforward enough to read without comments. `judge-defensive` comments repeat what the adjacent code already says, so none are retained.
- **Abstraction level: `judge-extract` wins.** A small private `Item` holder and direct helper methods fit the module. `judge-classes` adds parser interfaces, policy classes, and separate domain classes without enough behavior to justify them; `judge-inline`'s `Object[]` weakens type clarity.
- **Defensive checks: `judge-extract` wins.** Null input is checked at the shared calculation entry point; parsing helpers can assume non-null strings and valid field-array positions after their preceding checks. Extra null checks in `judge-defensive` do not improve the behavior contract.
