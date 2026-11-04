## Idiomatic patterns

Rust commonly expresses failure with `Result` and `?`, uses exhaustive `match` expressions and iterator chains, and makes ownership and lifetimes explicit. Traits, derives, and generics support reusable APIs.

## Not a defect by itself

Lifetime or generic annotations, an exhaustive match, and early return through `?` are not defects by themselves. Consider how the types and control flow communicate the contract.
