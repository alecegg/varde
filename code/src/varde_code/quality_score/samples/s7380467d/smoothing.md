# Style decisions

- **Granularity - `judge-inline` won.** Quote validation, rate selection, and arithmetic fit in one readable method. I kept the report loop local as well, avoiding the many one-use helpers in `judge-extract` and `judge-names`.
- **Naming - `judge-names` won in moderation.** I used `inputLine`, `declaredValue`, `baseRate`, and `RoundMoney` to make roles clear, while avoiding its unnecessarily long compound names.
- **Comments - `judge-inline` won.** The code is direct enough to read without narration; `judge-defensive` comments repeat the implementation and add noise.
- **Abstraction level - `judge-inline` with a small formatting helper.** Separate service, schedule, interface, and calculator classes from `judge-classes` are excessive for this single-file module. `FormatComponent` removes repeated formatting logic without obscuring the report layout.
