# C# seeded order item

This directory is self-contained for the C# corpus run: it includes the project file, manifest, strengthened behavior test, sensible implementation, five gaming variants, and mutation spec. The five gaming variants were hand-authored for this item in C#; they do not depend on `/private/tmp/qs-run1/csharp` to build or run.

## Variants

- `sensible.cs` is the seeded smoothed implementation.
- `tiny.cs` breaks row parsing, validation, pricing, result creation, and report formatting into 37 small single-purpose methods. The processing path calls those helpers directly; the public `Report` operation has its own helper tree.
- `namematched.cs` uses the same helper shape as `tiny.cs`, with descriptive helper names.
- `padded.cs` routes the public operations through wrapper layers and adds pass-through calculation steps.
- `monolith.cs` inlines rounding into its long order-processing method.
- `sizematched.cs` uses a `for-each` loop and two long public method bodies with inline parsing, validation, pricing, and report formatting. It retains both the empty-row check and subtotal rounding check. Its structure and variable names differ from `sensible.cs` while staying within 5% of its token count.

## Measured sizes and bands

Measured with `uv run python code/bench/quality-corpus/tools/item_targets.py code/bench/quality-corpus/seeded/csharp` (the tool prints function tokens and rows as `tokens/rows`). Layered targets: sensible 7-20 functions with 30-160 tokens per function; tiny and namematched 28-72 functions with 5-90 tokens and at most 10 rows; padded 14-22 functions, depth 3-6 and helper bodies 30-130 tokens; monolith 0.8x-1.6x sensible's file tokens and a main body larger than sensible's total function tokens; sizematched within ±10% of sensible file and function tokens.

| Version | File tokens | Functions | Per-function tokens/rows | Band misses |
| --- | ---: | ---: | --- | --- |
| sensible | 850 | 4 | Process 522/77; Report 209/17; RoundMoney 23/2; FormatMoney 25/2 | 7-20 functions; 30-160 tokens per function |
| tiny | 1,613 | 37 | Process 45/9; CheckInput 35/4; CreateState 12/1; ReadRows 35/4; ReadRow 34/5; ProcessFields 44/7; StoreFields 52/7; SplitColumns 21/1; CheckColumns 38/4; ReadSku 21/1; CheckSku 65/5; ReadQuantity 59/6; ReadPrice 59/6; CheckValues 52/5; AddProduct 71/7; AddLineAmount 28/2; ApplyPriceRules 77/8; RoundSubtotal 29/2; FindReduction 63/6; ReduceAmount 28/2; AddTax 27/2; FindCarriage 35/6; AddFinalAmount 33/2; CreateResult 71/5; Report 35/7; AppendReportContents 55/9; CheckOrder 26/4; StartReport 28/6; AddCount 36/2; AddSubtotal 26/1; AddDiscount 26/1; AddTaxLine 26/1; AddShipping 26/1; AddTotal 34/4; AppendMoney 43/4; FormatMoney 25/1; TrimReport 29/1 | Size exceeds sensible; function count, helper token sizes, and row limits are within the tiny bands. The checker reports report helpers as unreachable from its selected single entry; `Report` is a second public entry exercised by the behavior test. |
| padded | 1,000 | 13 | Process 15/1; StartOrder 15/1; PrepareOrder 15/1; ExecuteOrder 531/77; Report 15/1; BeginReport 15/1; PrepareReport 15/1; RenderReport 209/17; ApplyDiscount 17/1; ComputeTaxBase 12/1; CombineAmounts 22/1; RoundMoney 23/2; FormatMoney 25/2 | 14-22 functions; depth 3-6; helpers 30-130 tokens |
| monolith | 891 | 3 | Process 586/77; Report 209/17; FormatMoney 25/2 | One function; processing body does not exceed sensible's 779 total function tokens |
| namematched | 1,613 | 37 | Process 45/9; ValidateOrderText 35/4; InitializeOrderState 12/1; ConsumeInputLines 35/4; HandleInputLine 34/5; InterpretItemFields 44/7; StoreItemFields 52/7; SeparateItemFields 21/1; RequireThreeFields 38/4; ExtractSku 21/1; RegisterSku 65/5; ParseQuantityField 59/6; ParsePriceField 59/6; ValidateItemValues 52/5; StoreOrderItem 71/7; CalculateLineAmount 28/2; CalculateOrderCharges 77/8; NormalizeSubtotal 29/2; CalculateDiscount 63/6; SubtractDiscount 28/2; CalculateOrderTax 27/2; CalculateShippingFee 35/6; CalculateGrandTotal 33/2; BuildOrderResult 71/5; Report 35/7; WriteReportSections 55/9; ValidateReportArgument 26/4; CreateReportBuffer 28/6; WriteItemCount 36/2; WriteSubtotal 26/1; WriteDiscount 26/1; WriteTax 26/1; WriteShipping 26/1; WriteTotal 34/4; WriteCurrencyLine 43/4; FormatCurrency 25/1; FinishReportText 29/1 | Size exceeds sensible. The layered count, helper token, and row bands are met; same single-entry reachability note as tiny. |
| sizematched | 882 | 2 | Process 554/35; Report 257/13 | File size is 3.76% above sensible (within the requested 5%); the one-function target is missed because `Process` and `Report` are both required public methods |

The sensible entry name and signature findings in `item_targets.py` come from its generic `solution` convention; this sample's required API is `Original.Process` and `Original.Report`. The layered sensible target is also larger than this sample's four-function implementation. The tiny and namematched tree-shape checks use the highest-fanout method as the generic entry; their actual behavior-test entry is `Original.Process`.

## Strengthened behavior test and fairness

`behaviour_test.cs` is the strengthened item test. It extends the shared sample test with three discriminating cases that kill the `tax-rate`, `shipping-high-edge`, and `row-shape` mutants, plus midpoint-away rounding checks for unit price, line total, tax, and discount. Specifically it checks $1.03 tax (8.25% rounds to $0.08), discounted subtotal exactly $75.00 (free shipping), and rejection of a four-field row. The fixed shared test under `/private/tmp/qs-run1/csharp` was not edited.

The strengthened test was run against each local source and each supplied reference source. For each run, the candidate was copied as `Original.cs` alongside `BehaviourTest.cs` and `qssample.csproj`, then executed with `DOTNET_CLI_HOME=/tmp/qs-dotnet DOTNET_NOLOGO=1 dotnet run --project <temp>/qssample.csproj`.

| Source | Result | Detail |
| --- | --- | --- |
| sensible | PASS | |
| tiny | PASS | |
| padded | PASS | |
| monolith | PASS | |
| namematched | PASS | |
| sizematched | PASS | |
| supplied original | PASS | |
| judge-extract | PASS | |
| judge-inline | PASS | |
| judge-names | PASS | |
| judge-defensive | PASS | |
| judge-classes | FAIL | Its item `UnitPrice` remains 0.005 instead of rounding to 0.01 under the task's midpoint-away monetary rule. The judge file was not modified. |

## Verification

Run from the repository root:

```sh
uv run python code/bench/quality-corpus/tools/behaviour_runner.py --items code/bench/quality-corpus/seeded/csharp --check
uv run python code/bench/quality-corpus/tools/item_targets.py code/bench/quality-corpus/seeded/csharp
uv run python code/bench/quality-corpus/tools/mutate_check.py --item code/bench/quality-corpus/seeded/csharp --variant sensible.cs --mutants code/bench/quality-corpus/seeded/csharp/mutants.toml --json
```

Latest results: behavior runner passed all six local versions; mutation check passed with 20 killed, 0 survived, 0 equivalent, 0 broken, and 0 unapplied.

All six local sources have distinct MD5 hashes:

| Version | MD5 |
| --- | --- |
| sensible | `51fb8b5491aed0e7ccdcd89a9ce3934f` |
| tiny | `7a8e930818ec6fd3990be88f56d0204a` |
| padded | `54015e00698178957ea14d7cc1baaad4` |
| monolith | `94d9677a39ba63948e012bff4ed7384d` |
| namematched | `9b5955d0a60f0f5d268c2de311c54541` |
| sizematched | `e9e8852755893331d4b700a95977fd79` |
