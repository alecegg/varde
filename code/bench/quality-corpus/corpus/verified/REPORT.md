# Verified quality corpus (cd-networked-run)

Frozen 2026-10-18 by task `cd-networked-run`. Manifest digest `d79f3d0ee696916022451bf1d04f694e79cc65bc33166573701ce5724104097b`. Fetch cache `/Users/alec/.cache/varde/bench`; `$VARDE_BENCH_CACHE` must point there for mining and snapshot reads.

Reproduce with:

```sh
uv run python code/bench/quality-corpus/corpus/verified/cd_run.py pin
uv run python code/bench/quality-corpus/corpus/verified/cd_run.py roles
uv run python code/bench/quality-corpus/corpus/verified/cd_run.py fetch
uv run python code/bench/quality-corpus/corpus/verified/cd_artifacts.py mine
uv run python code/bench/quality-corpus/corpus/verified/cd_artifacts.py inputs
uv run python code/bench/quality-corpus/corpus/verified/cd_run.py report
```

Every pin is the default-branch tip at run time from `git ls-remote <url> HEAD`, except `redis/redis`, pinned on the BSD-3 `7.2` line (`refs/heads/7.2`) because later releases changed license. The license was read from the fetched pin's root license files and checked against the declared SPDX twice: once by `corpus/fetch.py`, whose verdict is recorded per repository in `verified.json`, and once by `cd_run.py`'s own text check (`LICENSE_MARKERS`), whose verdict decides `license_verified`. The tree digest is `git ls-tree -r --full-tree` over the pinned ref.

## Counts

| group | candidates | verified | roles | tier |
|---|---|---|---|---|
| Bash | 4 | 4 | calibration 3, held-out 1 | untiered (3 calibration repos) |
| C | 4 | 4 | calibration 3, held-out 1 | untiered (3 calibration repos) |
| C# | 3 | 3 | mutation-base 1, pairs 2 | report-only (0 calibration repos) |
| C++ | 4 | 4 | held-out 1, mutation-base 1, pairs 2 | report-only (0 calibration repos) |
| Dart | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| Elixir | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| Go | 3 | 3 | mutation-base 1, pairs 2 | report-only (0 calibration repos) |
| Haskell | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| Java | 4 | 3 | mutation-base 1, pairs 2 | report-only (0 calibration repos) |
| Kotlin | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| Lua | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| PHP | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| Python | 10 | 10 | calibration 5, held-out 1, mutation-base 1, none 1, pairs 2 | calibration floor met (5 repos) |
| Ruby | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| Rust | 4 | 4 | held-out 1, mutation-base 1, pairs 2 | report-only (0 calibration repos) |
| Scala | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| Solidity | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| Swift | 3 | 3 | calibration 2, held-out 1 | untiered (2 calibration repos) |
| TypeScript/JavaScript | 15 | 15 | calibration 8, held-out 1, mutation-base 1, none 3, pairs 2 | calibration floor met (8 repos) |

Total: 80 verified of 81 candidates, 1 excluded. Roles: calibration=39, held-out=16, mutation-base=7, none=4, pairs=14.

<!-- counts:start -->
```toml
total_candidates = 81
total_verified = 80
total_excluded = 1

[verified_by_language]
"Bash" = 4
"C" = 4
"C#" = 3
"C++" = 4
"Dart" = 3
"Elixir" = 3
"Go" = 3
"Haskell" = 3
"Java" = 3
"JavaScript" = 5
"Kotlin" = 3
"Lua" = 3
"PHP" = 3
"Python" = 10
"Ruby" = 3
"Rust" = 4
"Scala" = 3
"Solidity" = 3
"Swift" = 3
"TSX" = 3
"TypeScript" = 7

[verified_by_group]
"Bash" = 4
"C" = 4
"C#" = 3
"C++" = 4
"Dart" = 3
"Elixir" = 3
"Go" = 3
"Haskell" = 3
"Java" = 3
"Kotlin" = 3
"Lua" = 3
"PHP" = 3
"Python" = 10
"Ruby" = 3
"Rust" = 4
"Scala" = 3
"Solidity" = 3
"Swift" = 3
"TypeScript/JavaScript" = 15

[verified_by_role]
"calibration" = 39
"held-out" = 16
"mutation-base" = 7
"none" = 4
"pairs" = 14

[calibration_by_group]
"Bash" = 3
"C" = 3
"Dart" = 2
"Elixir" = 2
"Haskell" = 2
"Kotlin" = 2
"Lua" = 2
"PHP" = 2
"Python" = 5
"Ruby" = 2
"Scala" = 2
"Solidity" = 2
"Swift" = 2
"TypeScript/JavaScript" = 8

[candidates_by_group]
"Bash" = 4
"C" = 4
"C#" = 3
"C++" = 4
"Dart" = 3
"Elixir" = 3
"Go" = 3
"Haskell" = 3
"Java" = 4
"Kotlin" = 3
"Lua" = 3
"PHP" = 3
"Python" = 10
"Ruby" = 3
"Rust" = 4
"Scala" = 3
"Solidity" = 3
"Swift" = 3
"TypeScript/JavaScript" = 15
```
<!-- counts:end -->

## Repositories

| repository | language | SPDX | license file | pin | tree digest | tip bytes | cache bytes | role | status |
|---|---|---|---|---|---|---|---|---|---|
| Alamofire/Alamofire | Swift | MIT | LICENSE | `bda9ed57d729` | `fbfd41c8bdf2` | 22791271 | 1927116 | calibration | verified |
| App-vNext/Polly | C# | BSD-3-Clause | LICENSE | `3f3adad9d5af` | `689eb38fc0c0` | 9406797 | 2765557 | mutation-base | verified |
| BurntSushi/ripgrep | Rust | MIT | LICENSE-MIT | `3fce3b5bb023` | `7cb1858ab02f` | 3255965 | 725645 | mutation-base | verified |
| JamesNK/Newtonsoft.Json | C# | MIT | LICENSE.md | `52fa3aef1f2c` | `5174ce542513` | 16729609 | 8825551 | pairs | verified |
| JetBrains/Exposed | Kotlin | Apache-2.0 | LICENSE.txt | `09f814c61c22` | `c082cf925b83` | 137764311 | 6919761 | held-out | verified |
| Kong/kong | Lua | Apache-2.0 | LICENSE | `6605dd81630d` | `56464dad8800` | 17026300 | 5289771 | calibration | verified |
| Kotlin/kotlinx.coroutines | Kotlin | Apache-2.0 | LICENSE.txt | `7e0d1b3e9ca8` | `e6e1bb781f8b` | 13959348 | 8529121 | calibration | verified |
| LuaRocks/luarocks | Lua | MIT | COPYING | `f0916086ea5b` | `ecf7e67bfed5` | 12926687 | 5654711 | calibration | verified |
| OpenZeppelin/openzeppelin-contracts | Solidity | MIT | LICENSE | `b04d141ba4fe` | `d88e00f3680d` | 12680508 | 6942740 | calibration | verified |
| PostgREST/postgrest | Haskell | MIT | LICENSE | `c042567494b1` | `d2049ccfd176` | 4517769 | 2107751 | calibration | verified |
| Vectorized/solady | Solidity | MIT | LICENSE.txt | `2afba69bf67b` | `eabca9dac000` | 8369650 | 2805318 | calibration | verified |
| abseil/abseil-cpp | C++ | Apache-2.0 | LICENSE | `4cbb3d42f2b0` | `e70d59cfe257` | 11753381 | 8077606 | pairs | verified |
| apache/commons-lang | Java | Apache-2.0 | LICENSE.txt | `9c86ffe308e7` | `5b9800a004ef` | 10659821 | 14241942 | pairs | verified |
| apple/swift-nio | Swift | Apache-2.0 | LICENSE.txt | `eabcc14f9dcb` | `305e9dd87ff0` | 9280177 | 1780179 | calibration | verified |
| axios/axios | JavaScript | MIT | LICENSE | `326843a3902d` | `e10c8d8f5ef0` | 4607911 | 4296798 | calibration | verified |
| bats-core/bats-core | Bash | MIT | LICENSE.md | `f2a9f7449df1` | `9319e866224e` | 702316 | 308568 | calibration | verified |
| clap-rs/clap | Rust | MIT | LICENSE-MIT | `ccc89b838754` | `a9df9d9e0eea` | 3659306 | 15771636 | pairs | verified |
| colinhacks/zod | TypeScript | MIT | LICENSE | `680d19f7d1e0` | `29ec96648d46` | 15547246 | 12054519 | calibration | verified |
| composer/composer | PHP | MIT | LICENSE | `43f74517021a` | `7b942894af0f` | 3066822 | 1720214 | held-out | verified |
| curl/curl | C | curl | COPYING | `629646d9b798` | `ca2caa38f51c` | 18559250 | 5822010 | calibration | verified |
| dart-lang/http | Dart | BSD-3-Clause | LICENSE | `6e91ce3e73ab` | `1ef19f8e8431` | 4943762 | 1078888 | calibration | verified |
| django/django | Python | BSD-3-Clause | LICENSE | `d430084791a6` | `364e6ec2f30e` | 46199072 | 65536322 | pairs | verified |
| dotnet/roslyn | C# | MIT | License.txt | `3645b6aa36ad` | `6e6c4e5ba261` | 457729262 | 630408270 | pairs | verified |
| elixir-ecto/ecto | Elixir | Apache-2.0 | LICENSE.md | `ad8fda5dea76` | `4f9a3b52f15f` | 2636572 | 638556 | held-out | verified |
| elixir-lang/elixir | Elixir | Apache-2.0 | LICENSE | `e8c706061f1e` | `77088379ee2b` | 15102041 | 4086204 | calibration | verified |
| encode/httpx | Python | BSD-3-Clause | LICENSE.md | `b5addb64f016` | `1645b6ef8649` | 3321071 | 3944576 | calibration | verified |
| eslint/eslint | JavaScript | MIT | LICENSE | `e06fe87c41cc` | `8318cf4bb2ce` | 23735789 | 6850172 | calibration | verified |
| excalidraw/excalidraw | TSX | MIT | LICENSE | `4c37956ba5f0` | `35bc5bce4db7` | 56587252 | 35733051 | held-out | verified |
| expressjs/express | JavaScript | MIT | LICENSE | `a419aa735038` | `8c2b34b7a82e` | 710992 | 234472 | none | verified |
| fastify/fastify | TypeScript | MIT | LICENSE | `e03b48ba3cd9` | `fd5be24b050b` | 3019062 | 5714229 | calibration | verified |
| flutter/flutter | Dart | BSD-3-Clause | LICENSE | `84a33147edb0` | `4e81d6df1499` | 159620694 | 39080612 | held-out | verified |
| fmtlib/fmt | C++ | MIT | LICENSE | `fdf31252e61c` | `191d290e6df6` | 3160993 | 846765 | mutation-base | verified |
| folke/lazy.nvim | Lua | Apache-2.0 | LICENSE | `306a05526ada` | `525173d3d0a4` | 2609514 | 300623 | held-out | verified |
| foundry-rs/forge-std | Solidity | MIT | LICENSE-MIT | `b013eff2ac4f` | `a225d219e81b` | 1196505 | 192652 | held-out | verified |
| gin-gonic/gin | Go | MIT | LICENSE | `0f09c3a9b462` | `afde80837f81` | 886166 | 3321727 | pairs | verified |
| google/guava | Java | Apache-2.0 | LICENSE | `5e82f2f528fb` | `731d8a408c12` | 35572982 | 24749811 | pairs | verified |
| google/leveldb | C++ | BSD-3-Clause | LICENSE | `bb74ef739973` | `5a91d2e85933` | 993828 | 351677 | held-out | verified |
| haskell/cabal | Haskell | BSD-3-Clause | LICENSE | `f7ad3aa5ca69` | `9bf22427576c` | 16830226 | 4208158 | calibration | verified |
| jqlang/jq | C | MIT | COPYING | `633ae6058a05` | `63832b964238` | 4946381 | 1442125 | calibration | verified |
| ktorio/ktor | Kotlin | Apache-2.0 | LICENSE | `4016bdfe3225` | `0992565a3e33` | 76571727 | 23410019 | calibration | verified |
| laravel/framework | PHP | MIT | LICENSE.md | `e51b5fe16d6f` | `27085689f1bf` | 8614532 | 8636256 | calibration | verified |
| libuv/libuv | C | MIT | LICENSE | `a267f5688be2` | `41c8790525da` | 4748567 | 1733432 | held-out | verified |
| lodash/lodash | JavaScript | MIT | LICENSE | `2b5e6f7399a7` | `9501441a6831` | 4619643 | 850759 | calibration | verified |
| lysine-dev/okhttp | Java | Apache-2.0 | LICENSE.txt | `a66e3d227793` | `cd0bee2f52f8` | 7914735 | 2627730 | mutation-base | verified |
| mantinedev/mantine | TSX | MIT | LICENSE | `2d0a040f4201` | `b83afabe877c` | 21937476 | 10440571 | calibration | verified |
| microsoft/TypeScript | TypeScript | Apache-2.0 | LICENSE.txt | `2e9fb00f5f5c` | `5f921f1f0d34` | 216965943 | 1152068474 | pairs | verified |
| nestjs/nest | TypeScript | MIT | LICENSE | `2eb7be8dc341` | `1eea9f98fa89` | 7601531 | 66693621 | pairs | verified |
| nlohmann/json | C++ | MIT | LICENSE.MIT | `0e95fe8200ad` | `4eb1f345b49c` | 20489332 | 21846659 | pairs | verified |
| nvm-sh/nvm | Bash | MIT | LICENSE.md | `b1b3a0038c06` | `4349bdac55f5` | 1523835 | 623578 | calibration | verified |
| ohmyzsh/ohmyzsh | Bash | MIT | LICENSE.txt | `964ddf789b02` | `edef2c1b6822` | 7650596 | 3881746 | calibration | verified |
| pallets/click | Python | BSD-3-Clause | LICENSE.txt | `2247b35ea1c4` | `a76a55c4a333` | 1687127 | 3226164 | calibration | verified |
| pallets/flask | Python | BSD-3-Clause | LICENSE.txt | `d086db856be1` | `0bbfa2a1f90c` | 1785020 | 847916 | held-out | verified |
| pandas-dev/pandas | Python | BSD-3-Clause | LICENSE | `03e5d938adbd` | `bc56e21f93d5` | 27528743 | 73867320 | pairs | verified |
| phoenixframework/phoenix | Elixir | MIT | LICENSE.md | `1bae3a639f84` | `ff12e83d9c17` | 4406622 | 1504543 | calibration | verified |
| playframework/playframework | Scala | Apache-2.0 | LICENSE | `9f9c0cdc52e1` | `c8c743482587` | 12644612 | 4875394 | calibration | verified |
| prettier/prettier | JavaScript | MIT | LICENSE | `344d6dc42c80` | `1e94c355e670` | 25036574 | 8192513 | none | verified |
| prometheus/prometheus | Go | Apache-2.0 | LICENSE | `c052a79dc7fd` | `373db9df0ea6` | 30442022 | 29540941 | pairs | verified |
| psf/requests | Python | Apache-2.0 | LICENSE | `611c6162cbc4` | `cb591687bf3f` | 4451532 | 3205102 | none | verified |
| pydantic/pydantic | Python | MIT | LICENSE | `5adfeaaaea94` | `dfe29dc7d24c` | 11594962 | 16105282 | calibration | verified |
| pyenv/pyenv | Bash | MIT | LICENSE | `702ac01121aa` | `6a41134b92ab` | 8391730 | 1603632 | held-out | verified |
| pytest-dev/pytest | Python | MIT | LICENSE | `cb6ff97bcb14` | `6556dc97a205` | 7452811 | 2029008 | mutation-base | verified |
| python-attrs/attrs | Python | MIT | LICENSE | `ee66e7274852` | `5459107faebf` | 2076121 | 2591735 | calibration | verified |
| rails/rails | Ruby | MIT | MIT-LICENSE | `e9aab74b131f` | `e489d9e16fe4` | 40276540 | 13168773 | calibration | verified |
| redis/redis | C | BSD-3-Clause | COPYING | `ae987404da76` | `a8a9accc37ba` | 15564946 | 4067945 | calibration | verified |
| rrousselGit/riverpod | Dart | MIT | LICENSE | `87aad84b1afc` | `212b84e3b460` | 32463561 | 15230871 | calibration | verified |
| rubocop/rubocop | Ruby | MIT | LICENSE.txt | `a3b99c7c5944` | `79b221feabe5` | 16614614 | 4265383 | calibration | verified |
| scala/scala | Scala | Apache-2.0 | LICENSE | `d47c7568353f` | `03ff7964595d` | 26532422 | 10065189 | calibration | verified |
| scikit-learn/scikit-learn | Python | BSD-3-Clause | COPYING | `85593ca7a07a` | `652fbcb7a256` | 23918370 | 8875397 | calibration | verified |
| serde-rs/serde | Rust | MIT | LICENSE-MIT | `0db9b3b504bc` | `72682efbfde1` | 1388161 | 324420 | held-out | verified |
| shadcn-ui/ui | TSX | MIT | LICENSE.md | `d2fba50ee5b9` | `88e5464b4d41` | 51228524 | 18492367 | calibration | verified |
| sinatra/sinatra | Ruby | MIT | LICENSE | `cb22afd7902b` | `8968bca5453d` | 950171 | 377471 | held-out | verified |
| sindresorhus/got | TypeScript | MIT | license | `05b4476913da` | `83a2823ebf51` | 2581641 | 2125779 | calibration | verified |
| spf13/cobra | Go | Apache-2.0 | LICENSE.txt | `adbc8813901b` | `490831ff0e7e` | 705271 | 260021 | mutation-base | verified |
| symfony/symfony | PHP | MIT | LICENSE | `1eae1802fba5` | `ddb4143fba38` | 76926317 | 22259045 | calibration | verified |
| tokio-rs/tokio | Rust | MIT | LICENSE | `cdd9dae3aa50` | `e1af32a55e56` | 6375392 | 14988109 | pairs | verified |
| typelevel/cats | Scala | MIT | COPYING | `4a2ea736632c` | `629aa02f9bc7` | 4790868 | 1535314 | held-out | verified |
| typeorm/typeorm | TypeScript | MIT | LICENSE | `fe9239428751` | `67ff3d981156` | 12853601 | 3279840 | none | verified |
| vapor/vapor | Swift | MIT | LICENSE | `4245e700c869` | `fa6556007ad6` | 2044429 | 598505 | held-out | verified |
| vuejs/core | TypeScript | MIT | LICENSE | `bf5f0dd877dd` | `eca21343e008` | 6508619 | 1909061 | mutation-base | verified |
| yesodweb/yesod | Haskell | MIT | LICENSE | `4d3fcc460fab` | `e3dc45ac4f6d` | 1660220 | 614110 | held-out | verified |

## Excluded candidates and license failures

- `junit-team/junit-framework` (EPL-2.0): FetchError: EPL-2.0 is weak copyleft and is not in the permitted permissive set (validation-plan section 7: MIT, BSD, Apache-2.0, ISC, MPL-2.0 tolerated); license review not recorded, so the repository stays unverified and carries no role. No role assigned; pin `58516a5a0f41` left in the manifest for evidence.

## Declared SPDX corrected by the fetched license text

The manifest's per-repository `spdx` came from memory and is a claim, not a fact; these entries were corrected to the family the fetched license text identifies (all still permitted):

| repository | declared | verified | license file |
|---|---|---|---|
| App-vNext/Polly | MIT | BSD-3-Clause | LICENSE |

## corpus/fetch.py license-check differences

Most differences are MIT false negatives: `corpus/fetch.py` misses quoted canonical wording and alternate license filenames, and it rejects EPL text that mentions GPL as a secondary reference.

51 of 80 repositories passed the driver's text check and failed `corpus/fetch.py`'s:

| repository | SPDX | license file matched | corpus/fetch.py verdict |
|---|---|---|---|
| Alamofire/Alamofire | MIT | LICENSE | LICENSE text does not identify MIT |
| App-vNext/Polly | BSD-3-Clause | LICENSE | LICENSE text does not identify MIT |
| BurntSushi/ripgrep | MIT | LICENSE-MIT | LICENSE text does not identify MIT |
| JamesNK/Newtonsoft.Json | MIT | LICENSE.md | LICENSE text does not identify MIT |
| LuaRocks/luarocks | MIT | COPYING | LICENSE text does not identify MIT |
| OpenZeppelin/openzeppelin-contracts | MIT | LICENSE | LICENSE text does not identify MIT |
| PostgREST/postgrest | MIT | LICENSE | LICENSE text does not identify MIT |
| Vectorized/solady | MIT | LICENSE.txt | LICENSE text does not identify MIT |
| axios/axios | MIT | LICENSE | LICENSE text does not identify MIT |
| bats-core/bats-core | MIT | LICENSE.md | LICENSE text does not identify MIT |
| clap-rs/clap | MIT | LICENSE-MIT | LICENSE text does not identify MIT |
| colinhacks/zod | MIT | LICENSE | LICENSE text does not identify MIT |
| composer/composer | MIT | LICENSE | LICENSE text does not identify MIT |
| curl/curl | curl | COPYING | LICENSE text does not identify curl |
| dotnet/roslyn | MIT | License.txt | LICENSE text does not identify MIT |
| eslint/eslint | MIT | LICENSE | LICENSE text does not identify MIT |
| excalidraw/excalidraw | MIT | LICENSE | LICENSE text does not identify MIT |
| expressjs/express | MIT | LICENSE | LICENSE text does not identify MIT |
| fastify/fastify | MIT | LICENSE | LICENSE text does not identify MIT |
| fmtlib/fmt | MIT | LICENSE | LICENSE text does not identify MIT |
| foundry-rs/forge-std | MIT | LICENSE-MIT | LICENSE text does not identify MIT |
| gin-gonic/gin | MIT | LICENSE | LICENSE text does not identify MIT |
| jqlang/jq | MIT | COPYING | LICENSE text does not identify MIT |
| laravel/framework | MIT | LICENSE.md | LICENSE text does not identify MIT |
| libuv/libuv | MIT | LICENSE | LICENSE text does not identify MIT |
| lodash/lodash | MIT | LICENSE | LICENSE text does not identify MIT |
| mantinedev/mantine | MIT | LICENSE | LICENSE text does not identify MIT |
| nestjs/nest | MIT | LICENSE | LICENSE text does not identify MIT |
| nlohmann/json | MIT | LICENSE.MIT | LICENSE text does not identify MIT |
| nvm-sh/nvm | MIT | LICENSE.md | LICENSE text does not identify MIT |
| ohmyzsh/ohmyzsh | MIT | LICENSE.txt | LICENSE text does not identify MIT |
| phoenixframework/phoenix | MIT | LICENSE.md | LICENSE text does not identify MIT |
| prettier/prettier | MIT | LICENSE | LICENSE text does not identify MIT |
| pydantic/pydantic | MIT | LICENSE | LICENSE text does not identify MIT |
| pyenv/pyenv | MIT | LICENSE | LICENSE text does not identify MIT |
| pytest-dev/pytest | MIT | LICENSE | LICENSE text does not identify MIT |
| python-attrs/attrs | MIT | LICENSE | LICENSE text does not identify MIT |
| rails/rails | MIT | MIT-LICENSE | LICENSE text does not identify MIT |
| rrousselGit/riverpod | MIT | LICENSE | LICENSE text does not identify MIT |
| rubocop/rubocop | MIT | LICENSE.txt | LICENSE text does not identify MIT |
| serde-rs/serde | MIT | LICENSE-MIT | LICENSE text does not identify MIT |
| shadcn-ui/ui | MIT | LICENSE.md | LICENSE text does not identify MIT |
| sinatra/sinatra | MIT | LICENSE | LICENSE text does not identify MIT |
| sindresorhus/got | MIT | license | LICENSE text does not identify MIT |
| symfony/symfony | MIT | LICENSE | LICENSE text does not identify MIT |
| tokio-rs/tokio | MIT | LICENSE | LICENSE text does not identify MIT |
| typelevel/cats | MIT | COPYING | LICENSE text does not identify MIT |
| typeorm/typeorm | MIT | LICENSE | LICENSE text does not identify MIT |
| vapor/vapor | MIT | LICENSE | LICENSE text does not identify MIT |
| vuejs/core | MIT | LICENSE | LICENSE text does not identify MIT |
| yesodweb/yesod | MIT | LICENSE | LICENSE text does not identify MIT |

## Category (c): mined refactor pairs

Completed mining from 13 pinned `pairs` repositories; 1 are time-capped, partial. Target is 6 pairs per release language.

| language | completed repos | partial repos | commits walked | intent matches | accepted | vs target |
|---|---|---|---|---|---|---|
| cpp | 2 | 0 | 9185 | 501 | 130 | target met |
| csharp | 1 | 1 | 1927 | 30 | 8 | target met |
| go | 2 | 0 | 20981 | 557 | 204 | target met |
| java | 2 | 0 | 17641 | 492 | 163 | target met |
| python | 2 | 0 | 74536 | 1777 | 617 | target met |
| rust | 2 | 0 | 14030 | 258 | 25 | target met |
| typescript | 2 | 0 | 61831 | 1004 | 269 | target met |

Languages short of 6 pairs: none.

`dotnet/roslyn`: **time-capped, partial**; 0 Roslyn pairs were persisted before the cap. The mining process reached its 50-minute time budget before writing its final JSONL and stats; no Roslyn pair records were persisted.
C# has 8 accepted pairs from completed repositories, meeting the 6-pair target.

Filter pass rates (passed / evaluated at that stage):

| language | parent | intent | file limit | parse | function limit | generated | public feature |
|---|---|---|---|---|---|---|---|
| cpp | 8232/9185 | 501/8232 | 310/501 | 249/310 | 151/249 | 151/151 | 130/151 |
| csharp | 1757/1927 | 30/1757 | 17/30 | 13/17 | 9/13 | 9/9 | 8/9 |
| go | 15537/20981 | 557/15537 | 391/557 | 366/391 | 239/366 | 235/239 | 204/235 |
| java | 17398/17641 | 492/17398 | 335/492 | 324/335 | 176/324 | 176/176 | 163/176 |
| python | 70771/74536 | 1777/70771 | 1206/1777 | 1099/1206 | 790/1099 | 788/790 | 617/788 |
| rust | 11551/14030 | 258/11551 | 188/258 | 44/188 | 25/44 | 25/25 | 25/25 |
| typescript | 44754/61831 | 1004/44754 | 738/1004 | 511/738 | 296/511 | 289/296 | 269/289 |

## Category (d): mutation inputs

Selected 168 functions (target 20 per release language) into `corpus/verified/mutation-inputs/<language>/`; each input is one function, 10-60 lines, parseable on its own, with provenance in the language's `provenance.json` and any license header kept as a `.license.txt` sidecar.

| language | mutation-base repos | inputs | license headers kept | vs target |
|---|---|---|---|---|
| cpp | fmtlib/fmt | 24 | 22 | target met |
| csharp | App-vNext/Polly | 24 | 0 | target met |
| go | spf13/cobra | 24 | 24 | target met |
| java | lysine-dev/okhttp | 24 | 24 | target met |
| python | pytest-dev/pytest | 24 | 0 | target met |
| rust | BurntSushi/ripgrep | 24 | 0 | target met |
| typescript | vuejs/core | 24 | 0 | target met |

## Notes

- Bash: untiered (3 calibration repos).
- C: untiered (3 calibration repos).
- C#: report-only (0 calibration repos).
- C++: report-only (0 calibration repos).
- Dart: untiered (2 calibration repos).
- Elixir: untiered (2 calibration repos).
- Go: report-only (0 calibration repos).
- Haskell: untiered (2 calibration repos).
- Java: report-only (0 calibration repos).
- Kotlin: untiered (2 calibration repos).
- Lua: untiered (2 calibration repos).
- PHP: untiered (2 calibration repos).
- Python: calibration floor met (5 repos).
- Ruby: untiered (2 calibration repos).
- Rust: report-only (0 calibration repos).
- Scala: untiered (2 calibration repos).
- Solidity: untiered (2 calibration repos).
- Swift: untiered (2 calibration repos).
- TypeScript/JavaScript: calibration floor met (8 repos).
- The calibration floor is 5 repositories per release language (validation-plan section 7); Python and TypeScript/JavaScript meet the floor after this reassignment. Other language groups remain report-only or untiered.
- No repository carries the `history` role in this run, so no `history_cutoffs` are pinned; the role and its T-12m/T-24m/T-36m cutoffs stay for the later history-validation task.
- `pairs/mined/` holds candidate records only; `pair_groups` in the manifest stays empty because registering every mined candidate there would add hundreds of groups for a set the panel has not labelled yet.
- `roles.py --check-reservations` reports no conflict; the four call-resolution repositories carry no quality-corpus role.
- `lysine-dev/okhttp`, the Java `mutation-base` repository, is predominantly Kotlin at its pin (573 `.kt` files, 71 `.java` files); its Java inputs come from its Java sources.
- Pins are brute-forced tips, so they will move upstream; `verified.json` records each pin and tree digest, and `corpus/fetch.py` fails a cached checkout whose pinned tree no longer matches.
- `jqlang/jq`: COPYING bundles notices for BSD-2-Clause, curl.
- `typelevel/cats`: COPYING bundles notices for Apache-2.0, BSD-2-Clause.

