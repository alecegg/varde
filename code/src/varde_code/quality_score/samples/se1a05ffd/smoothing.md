# Style disputes

- **Validation and processing structure:** `judge-inline` wins over `judge-extract` and `judge-classes`. Keeping row validation in one readable loop avoids many tiny helpers and a service/interface layer. `ProcessOrder` validates first, then handles only pricing and reporting.
- **Names:** `judge-inline` wins over `judge-names`. Short names such as `subtotal`, `discountedSubtotal`, and `unit` are clear in this small module; spelling out “stock keeping unit” and “merchandise subtotal cents” adds noise.
- **Comments:** `judge-inline` wins over `judge-defensive`. Comments are limited to the one non-obvious point, that quantity parsing is safe after validation. The surrounding code already explains itself.
- **Abstraction level:** `judge-inline` wins over `judge-extract` and `judge-classes`. The order line type is useful shared data, and named pricing helpers keep policy calculations distinct. More parsing, reporting, policy, and service wrappers would fragment a small fixed catalog workflow.
- **Branch style:** `judge-inline` wins over `judge-defensive` and `judge-names`. Early returns in shipping selection express the three thresholds directly without nested branches or a redundant final condition.
