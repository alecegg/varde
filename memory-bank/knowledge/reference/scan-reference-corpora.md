---
type: reference
description: Read-only reference repositories per language used to measure scan-rule false positives.
paths:
  - memory-bank/knowledge/reference/scan-reference-corpora.md
---

# Scan reference corpora

Each repository is a shallow clone (`git clone --depth 1 https://github.com/<owner>/<name>.git`, then `git checkout <commit>` if the pinned commit differs from the tip) kept read-only. Measurement indexes copies under `$TMPDIR`. Counts come from `find` over source files, excluding vendored trees.

## Go

| Repository | Commit | Licence | `.go` files |
|---|---|---|---|
| caddyserver/caddy | d588d5c8f0a48a44851a218bbfc3d6edc0e4be17 | Apache-2.0 | 378 |
| gohugoio/hugo | 0732eadd5aead94d4bd4674d87e9bfc79aaf10a7 | Apache-2.0 | 915 |
| traefik/traefik | 6e722fee4ed4ba16c4c039eb0721fdedb9d558b8 | MIT | 775 |

Combined: 2068 files.

## Compiled, JVM, .NET, Apple and Dart languages

Counts are files of the language's extensions (C and C++ include headers); `semantic-kernel` was already indexed.

| Language | Repository | Commit | Licence | Files |
|---|---|---|---|---|
| Java | google/guava | 6b3a8d7498a7fde122967ba37a023ba3dcb47792 | Apache-2.0 | 3275 |
| Java | junit-team/junit5 | fc4e0383c9c14e444de316649de16a2d49e8b68e | EPL-2.0 | 1801 |
| Java | apache/commons-lang | 32dc4c501e3acba29d53a466eebd611bb2f093a5 | Apache-2.0 | 629 |
| Java and C# | microsoft/semantic-kernel | c028a0c7dc4f0814cdcbaba9d998f187a41197bf | MIT | .java 0, .cs 2412 |
| Kotlin | square/okhttp | 42e5888d45623662c138ed27e80ea28bbe0aa5cc | Apache-2.0 | 573 |
| Kotlin | JetBrains/Exposed | 11e9c120ce607af10a8597ed8948e07d80cf395f | Apache-2.0 | 939 |
| Kotlin | ktorio/ktor | 4717dd5fe8270a40fc97ba0b03bb63f722717786 | Apache-2.0 | 2435 |
| Scala | playframework/playframework | 2647258feae7d9f682fa6f079e20c6b57176df3d | Apache-2.0 | 852 |
| Scala | http4s/http4s | 7ae5b1ea14c6df3f9b6b00ba5a74b2ff7adcde2d | Apache-2.0 | 667 |
| Scala | typelevel/cats | 4a2ea736632c64aaf2e4915e6922e3585379382f | MIT | 835 |
| C# | JamesNK/Newtonsoft.Json | 52fa3aef1f2cadcd3a3f874251eddc98d3efbbaa | MIT | 951 |
| C# | App-vNext/Polly | e4476096da5be34e1ec32c024c24289af3ef72e6 | BSD-3-Clause | 801 |
| C# | serilog/serilog | bebc7719004f76187ae72e64ce138ec2540f2070 | Apache-2.0 | 216 |
| Swift | Alamofire/Alamofire | bda9ed57d72988a3a2ada33d824583541f86eac6 | MIT | 101 |
| Swift | apple/swift-nio | e12881f2a69168c984b890eec7a10de70441d2d7 | Apache-2.0 | 555 |
| Swift | pointfreeco/swift-composable-architecture | bc2db5ba8ad3a47deba5db32fa340637ba6c9a76 | MIT | 798 |
| C | redis/redis | 3c7e951c3dc13fdeb905092e4a921ca7823e6faa | see LICENSE.txt (AGPL option) | 788 |
| C | curl/curl | 098d3a0d4044d8a3f0a8617a5a5a30cde90fba26 | curl licence | 1052 |
| C | libuv/libuv | ec1928832534e18b2941d0ec629623a3e390cec4 | MIT | 369 |
| C++ | nlohmann/json | 74aefc3486c6dcd03a5a039d86f1ac8d146c0f74 | MIT | 468 |
| C++ | google/leveldb | bb74ef739973a70ca9f0d90788a1da89b788c0ad | BSD-3-Clause | 132 |
| C++ | fmtlib/fmt | 35c58f084e7cd79b51997439cff68346f4c724c0 | MIT | 73 |
| Dart | rrousselGit/riverpod | 1efba1c8609571dc8d51161bec2a7d155bfce957 | MIT | 1303 |
| Dart | fluttercommunity/plus_plugins | 907994b0e52c2c11ae2f2ccc08d0658e1c73dbaf | BSD-3-Clause | 138 |
| Dart | dart-lang/http | 23f8574cdfce93c3bb0c6d83d92167d92b9824d5 | BSD-3-Clause | 339 |

Per-language combined counts: Java 5705 (+ semantic-kernel), Kotlin 3947, Scala 2354, C# 1968 + 2412 (semantic-kernel), Swift 1454, C 2209, C++ 673, Dart 1780.

## Scripting and remaining languages

Bash counts `.sh`, `.bash` and `.bats` files. Elixir counts `.ex` and `.exs`. Licences matter only for local read-only measurement.

| Language | Repository | Commit | Licence | Files |
|---|---|---|---|---|
| Ruby | rubocop/rubocop | 70f46e3ebce50f69e1815231e65a6a777b3ec50f | MIT | 1791 |
| Ruby | sinatra/sinatra | cb22afd7902b566b6eaba6c4ea89739494a65d12 | MIT | 147 |
| Ruby | jekyll/jekyll | 541d8b2ee75c8907de4744d4b87a7a6f1f997cae | MIT | 162 |
| PHP | laravel/framework | 01ac36d93ae87e0f95b860bdba62675841a40228 | MIT | 3152 |
| PHP | composer/composer | 43f74517021a59ed4054a801c1472ef66355c49a | MIT | 602 |
| PHP | guzzle/guzzle | 93939470950a9b11e2e84204166ef5e048c55fe4 | MIT | 137 |
| Lua | Kong/kong | 2d2e67ea7a90cc9d81c53177e9fdbe61bd142236 | Apache-2.0 | 1312 |
| Lua | folke/lazy.nvim | 306a05526ada86a7b30af95c5cc81ffba93fef97 | Apache-2.0 | 65 |
| Lua | nvim-telescope/telescope.nvim | 40aedd8a68c78a656a10a8d62d80c54af59420fb | MIT | 77 |
| Lua | neovim/nvim-lspconfig | c59fc922f718fa055f69f5f3bc888f23211571eb | Apache-2.0 | 865 |
| Bash | nvm-sh/nvm | b1b3a0038c0666c7436cb5d383608b4b72c8300b | MIT | 8 |
| Bash | bats-core/bats-core | 0c92eb4c418d59fcb1a1a8c1d7a015f8149689f2 | MIT | 287 |
| Bash | bash-it/bash-it | 81929690975f9a7ea3c50b87265f2959327bb0a5 | MIT | 363 |
| Bash | pyenv/pyenv | 8000f98f4bd1f86dfca4ee91930506953c6e6f73 | MIT | 59 |
| Elixir | phoenixframework/phoenix | 5a9e92f34bc763231a356f7011de0387d29d863a | MIT | 206 |
| Elixir | elixir-ecto/ecto | 94d69279c517347ff0962b138f4ccd0556486ae2 | Apache-2.0 | 126 |
| Elixir | elixir-plug/plug | 73404f851852a00ffb2014be95d4598900fa77b8 | Apache-2.0 | 78 |
| Elixir | livebook-dev/livebook | 5190786bf493e435a5678056f749d28fea290f6f | Apache-2.0 | 443 |
| Elixir | oban-bg/oban | 06846d775f7fd85722d1862cb995984ef0b65321 | Apache-2.0 | 124 |
| Haskell | jgm/pandoc | e51c9c6054c8f4ec5c3209d5abe10939dfe2963e | GPL-2.0-or-later | 366 |
| Haskell | koalaman/shellcheck | 98deabe126a26861fb02aa2b431eaf31e39e6abe | GPL-3.0 | 31 |
| Haskell | PostgREST/postgrest | f7abddf57fd9177608175f6758f1f28d8d94690b | MIT | 172 |
| Solidity | OpenZeppelin/openzeppelin-contracts | b0c7bd5a09152a635687070648bdb28571812194 | MIT | 419 |
| Solidity | Uniswap/v3-core | d0831dc6b8a318df3872b6d68f6de135c9f3ec29 | BUSL-1.1 | 69 |
| Solidity | aave/aave-v3-core | 782f51917056a53a2c228701058a6c3fb233684a | BUSL-1.1 | 132 |
| Solidity | transmissions11/solmate | 89365b880c4f3c786bdd453d4b8e8fe410344a69 | AGPL-3.0 (per upstream; LICENSE not matched by grep) | 59 |

Per-language combined counts: Ruby 2100, PHP 3891, Lua 2319, Bash 717, Elixir 977, Haskell 569, Solidity 679.

Corpora that predate this page (Rust: varde, fallow, oh-my-pi, ast-grep; Python: crewAI, langgraph, hermes-agent) are unchanged. Repository names are `owner/name` on GitHub.
