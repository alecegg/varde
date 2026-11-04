# Java seeded item

## Build recipe

This directory is self-contained: its Java sources, shared behavior harness,
profile, and mutation specification are all stored here. The variants were
hand-authored. Rebuilding and checking them does not depend on
`/private/tmp/qs-run1` or any other external sample directory. `sensible.java`
is the retained smoothed implementation. `tiny.java` routes its process
formatter through 29 forwarding methods and also splits inventory-row handling,
order-line validation/pricing, and total calculations into small helpers.
`namematched.java` uses the original forwarding-chain shape with domain-specific
names such as `calculateShippingTier` and `applyGroupDiscount`; those methods
only forward the same value, despite their business-operation names. `padded.java` adds
formatting, rounding, tax, discount, and line-price wrappers. `monolith.java` inlines parsing, validation, pricing, and totals into one
dominant `calculate` method, while retaining the three required public API
methods. A literal one-method implementation is impossible because the contract
requires distinct `validate(String, String)`, `process(String, String)`, and
`report(String, String)` methods. The fifth extracted function is the `Item`
constructor. `sizematched.java` is a distinct unstructured control: it also puts
its parsing and calculation in one long method, with redundant cent-preserving
assignments to bring the measured file size within 5% of sensible.

The copied test harness class is package-private so `mutate_check.py` can
compile its conventional `behaviour_test.java` filename. `Original` is also
package-private because the mutator compiles it under `solution.java`.

Behavior command for each variant (copy its source to `Original.java` and the
test to `BehaviourTest.java` in a temporary directory first):

```sh
/opt/homebrew/bin/javac Original.java BehaviourTest.java
/opt/homebrew/bin/java -cp . BehaviourTest
```

Mutation command:

```sh
PATH=/opt/homebrew/bin:$PATH uv run python code/bench/quality-corpus/tools/mutate_check.py \
  --item code/bench/quality-corpus/seeded/java \
  --variant sensible.java \
  --mutants code/bench/quality-corpus/seeded/java/mutants.toml --jobs 4
```

All six behavior runs passed. Mutation check: 24 killed, 0 survived, 0 broken,
0 unapplied, 0 equivalent.

## Measured targets

Values come from `uv run python code/bench/quality-corpus/tools/item_targets.py
code/bench/quality-corpus/seeded/java`:

| Variant | Tokens | Functions | Result | Band misses |
| --- | ---: | ---: | --- | --- |
| sensible | 1377 | 21 | drift | 7-20 functions; several methods under 30 tokens and `inventory`/`orderLine` exceed 160 |
| tiny | 2147 | 60 | ok | none; split row parsing, stock insertion, order validation, line pricing, and totals into small helpers |
| padded | 1539 | 30 | drift | 14-22 functions; methods including `validate` and added wrappers are below the 30-token helper minimum; helper-count and fanout targets also drift |
| monolith | 1255 | 5 | ok | no reported metric violations; one dominant calculation method plus the required APIs and `Item` constructor |
| namematched | 1899 | 50 | drift | original `inventory` and `orderLine` remain over 90 tokens, among other inherited helper-size misses; forwarding names are descriptive but their bodies remain trivial |
| sizematched | 1335 | 5 | drift | 3.1% below sensible (within the requested ±5%); the file has one long calculation method plus the required APIs and `Item` constructor |

The sensible rule's 20-function ceiling is exceeded because this sample needs
three public operations, a typed item holder, parsing and validation helpers,
calculation helpers, and two output formats. The overlong parsing and order
pricing methods also reflect necessary input checks and the sample's shared
behavior contract. The layered tree bands assume smaller tasks; the required
public surface and business rules constrain further reduction.


All six behavior-test runs passed. The mutation check reported 24 killed, 0 survived, 0 broken, 0 unapplied, and 0 equivalent. The five gaming/control sources have distinct MD5 digests: tiny `48b980f7881a4e941f5589ddc94e5458`, padded `71fb5b49c80d04719b293365700b3938`, monolith `1bc24a4d967afcb3ec9112fafe4f8239`, namematched `209bd38065cbf38f3cddbfff34f6981a`, and sizematched `e0f0e1cbad6d2e69649ec97b309665b7`.
