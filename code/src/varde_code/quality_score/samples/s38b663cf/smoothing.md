# Style disputes

- **Method granularity:** `judge-inline` won over `judge-extract`'s chain of parsing and formatting helpers. `ProcessLine` keeps the validation flow visible; monetary calculation is factored into one shared helper because both public total calculation and booking reports need the same arithmetic.
- **Naming length:** `judge-names` won over `original`'s one-letter locals, with shorter names than `judge-names` where the type already provides context. Names such as `discountedSubtotal` and `IsValidQuantity` clarify meaning without repeating “ticket”, “currency”, or “booking” throughout.
- **Comments:** `judge-defensive` lost. The conditions and method names make this short flow clear; line-by-line comments repeat what the code already says and make it harder to scan.
- **Abstraction level:** `judge-extract` won a limited extraction for shared amount calculation, while its multi-stage parsing pipeline lost. `judge-classes` lost: the fixed three-class price map and fee rule do not need a service layer, strategy types, or mutable domain objects.
- **Report construction:** `judge-inline` won the direct string assembly approach in spirit, while `judge-extract`'s line-oriented join was chosen for the report. It keeps the seven output lines together and avoids repeated newline concatenation.
