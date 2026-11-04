# Style decisions

- **Function granularity: `judge-extract` wins, trimmed.** Its named pricing helpers make validation and pricing stages easy to follow. The final version keeps useful boundaries (`readOrder`, `priceItems`, `discountFor`, `shippingFor`) while folding one-use wrappers and avoiding a helper that hides the subtotal calculation.
- **Naming length: `judge-extract` wins.** Short domain names such as `OrderInput`, `PricedItem`, `subtotal`, and `discountFor` are clear without the expanded names in `judge-names`.
- **Comments: `judge-inline` wins.** The code is clearest without narration on obvious operations; no comments are needed to explain the pricing stages.
- **Abstraction level: `judge-extract` wins.** Plain functions and records suit this single order-processing flow. The policy classes in `judge-classes` add indirection without a second implementation or runtime need.
- **Validation style: `judge-defensive` wins.** Explicit numeric type checks and `Set` membership make validation precise and avoid inherited object keys being mistaken for duplicate SKUs. Report formatting stays direct because its public contract accepts the typed result.
