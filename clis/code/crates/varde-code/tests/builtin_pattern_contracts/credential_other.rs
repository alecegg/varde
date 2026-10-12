use super::Case;

/// Fixture contracts for other-language hardcoded-credential rules.
///
/// Elixir module attributes (`@api_key "..."`) and Solidity contract state
/// variables (`$$$MOD string ...`, which ignores `public`, `constant` and
/// `immutable`) have their own rules; the binding and local forms keep theirs.
///
/// Raw and multiline literals are invalid cases: Elixir heredocs (`"""..."""`)
/// and sigils (`~s(...)`), Solidity `unicode"..."`. Interpolated Elixir forms
/// (`~s` with `#{...}`) stay valid; Haskell has no raw form, and its multi-line
/// string gaps keep the backslash, which the shared VAL rejects.
pub fn cases() -> Vec<Case> {
    let elixir = Case::new(
        "hardcoded-credential-elixir",
        &["elixir"],
        vec![
            "api_key = \"9abcdefghijklmno\"".to_string(),
            "password = \"9abcdefghijklmno\"".to_string(),
            "session_token = \"abcdefg9hijklmno\"".to_string(),
            "api_key = \"\"\"\n9abcdefghijklmno\n\"\"\"".to_string(),
        ],
        vec![
            "api_key = \"9abcdefghijklmn\"".to_string(),
            "api_key = \"abcdefghijklmnop\"".to_string(),
            "not_the_key = \"9abcdefghijklmno\"".to_string(),
            "api_key = System.get_env(\"API_KEY\")".to_string(),
            "api_key = \"abc#{secret}9abcdefghijklmno\"".to_string(),
            "config = %{api_key: \"9abcdefghijklmno\"}".to_string(),
        ],
    );
    let elixir_attribute = Case::new(
        "hardcoded-credential-elixir-attribute",
        &["elixir"],
        vec![
            "defmodule M do\n  @api_key \"9abcdefghijklmno\"\nend".to_string(),
            "defmodule M do\n  @password \"abcdefg9hijklmno\"\nend".to_string(),
            "defmodule M do\n  @session_token \"abcdefghijklmno9\"\nend".to_string(),
            "defmodule M do\n  @api_key \"\"\"\n9abcdefghijklmno\n\"\"\"\nend".to_string(),
            "defmodule M do\n  @api_key ~s(9abcdefghijklmno)\nend".to_string(),
        ],
        vec![
            "defmodule M do\n  @api_key \"9abcdefghijklmn\"\nend".to_string(),
            "defmodule M do\n  @api_key \"abcdefghijklmnop\"\nend".to_string(),
            "defmodule M do\n  @moduledoc \"9abcdefghijklmno\"\nend".to_string(),
            "defmodule M do\n  @api_key System.get_env(\"API_KEY\")\nend".to_string(),
            "defmodule M do\n  @api_key ~s(#{secret}9abcdefghijklmno)\nend".to_string(),
            // A plain binding belongs to the binding rule.
            "defmodule M do\n  def f do\n    api_key = \"9abcdefghijklmno\"\n  end\nend"
                .to_string(),
        ],
    );
    let haskell = Case::new(
        "hardcoded-credential-haskell",
        &["haskell"],
        vec![
            "api_key = \"9abcdefghijklmno\"".to_string(),
            "password = \"9abcdefghijklmno\"".to_string(),
            "session_token = \"abcdefg9hijklmno\"".to_string(),
        ],
        vec![
            "api_key = \"9abcdefghijklmn\"".to_string(),
            "api_key = \"abcdefghijklmnop\"".to_string(),
            "not_the_key = \"9abcdefghijklmno\"".to_string(),
            "api_key = getEnv \"API_KEY\"".to_string(),
            "c = Config { api_key = \"9abcdefghijklmno\" }".to_string(),
            "api_key = \"abc\\\n          \\9abcdefghijklmno\"".to_string(),
        ],
    );
    let haskell_annotated = Case::new(
        "hardcoded-credential-haskell-annotated",
        &["haskell"],
        vec![
            "api_key = \"9abcdefghijklmno\" :: String".to_string(),
            "token = \"9abcdefghijklmno\" :: String".to_string(),
        ],
        vec![
            "api_key = \"9abcdefghijklmn\" :: String".to_string(),
            "api_key = \"abcdefghijklmnop\" :: String".to_string(),
            "not_the_key = \"9abcdefghijklmno\" :: String".to_string(),
            "api_key = getEnv \"API_KEY\" :: IO String".to_string(),
            "api_key = \"9abcdefghijklmno\"".to_string(),
        ],
    );
    let solidity = Case::new(
        "hardcoded-credential-solidity",
        &["solidity"],
        vec![
            "string constant api_key = \"9abcdefghijklmno\";".to_string(),
            "string constant password = \"9abcdefghijklmno\";".to_string(),
            "string constant session_token = \"abcdefg9hijklmno\";".to_string(),
            "string constant api_key = unicode\"9abcdefghijklmno\";".to_string(),
        ],
        vec![
            "string constant api_key = \"9abcdefghijklmn\";".to_string(),
            "string constant api_key = \"abcdefghijklmnop\";".to_string(),
            "string constant not_the_key = \"9abcdefghijklmno\";".to_string(),
            "string constant api_key = getSecret();".to_string(),
            "uint256 constant api_key = 1234567890123456;".to_string(),
        ],
    );
    let solidity_local = Case::new(
        "hardcoded-credential-solidity-local",
        &["solidity"],
        vec![
            "contract C { function f() public { string memory api_key = \"9abcdefghijklmno\"; } }"
                .to_string(),
            "contract C { function f() public { string memory password = \"9abcdefghijklmno\"; } }"
                .to_string(),
        ],
        vec![
            "contract C { function f() public { string memory api_key = \"9abcdefghijklmn\"; } }"
                .to_string(),
            "contract C { function f() public { string memory api_key = \"abcdefghijklmnop\"; } }"
                .to_string(),
            "contract C { function f() public { string memory not_the_key = \"9abcdefghijklmno\"; } }"
                .to_string(),
            "contract C { function f() public { string memory api_key = getSecret(); } }"
                .to_string(),
            "contract C { function f() public { s.api_key = \"9abcdefghijklmno\"; } }".to_string(),
        ],
    );
    let solidity_assignment = Case::new(
        "hardcoded-credential-solidity-assignment",
        &["solidity"],
        vec![
            "contract C { function f() public { api_key = \"9abcdefghijklmno\"; } }".to_string(),
            "contract C { function f() public { token = \"9abcdefghijklmno\"; } }".to_string(),
        ],
        vec![
            "contract C { function f() public { api_key = \"9abcdefghijklmn\"; } }".to_string(),
            "contract C { function f() public { api_key = \"abcdefghijklmnop\"; } }".to_string(),
            "contract C { function f() public { not_the_key = \"9abcdefghijklmno\"; } }"
                .to_string(),
            "contract C { function f() public { api_key = getSecret(); } }".to_string(),
            "contract C { function f() public { api_key = vm.envString(\"API_KEY\"); } }"
                .to_string(),
            "contract C { function f() public { s.api_key = \"9abcdefghijklmno\"; } }".to_string(),
        ],
    );
    let solidity_state = Case::new(
        "hardcoded-credential-solidity-state",
        &["solidity"],
        vec![
            "contract C { string public api_key = \"9abcdefghijklmno\"; }".to_string(),
            "contract C { string private immutable password = \"abcdefg9hijklmno\"; }".to_string(),
            "contract C { string constant session_token = \"abcdefghijklmno9\"; }".to_string(),
            "contract C { string internal client_secret = \"9abcdefghijklmno\"; }".to_string(),
            "contract C { string public api_key = unicode\"9abcdefghijklmno\"; }".to_string(),
        ],
        vec![
            "contract C { string public api_key = \"9abcdefghijklmn\"; }".to_string(),
            "contract C { string public api_key = \"abcdefghijklmnop\"; }".to_string(),
            "contract C { string public not_the_key = \"9abcdefghijklmno\"; }".to_string(),
            "contract C { string public api_key = getSecret(); }".to_string(),
            "contract C { uint256 public api_key = 1234567890123456; }".to_string(),
            // A local declaration belongs to the local rule.
            "contract C { function f() public { string memory api_key = \"9abcdefghijklmno\"; } }"
                .to_string(),
        ],
    );
    vec![
        elixir,
        elixir_attribute,
        haskell,
        haskell_annotated,
        solidity,
        solidity_local,
        solidity_assignment,
        solidity_state,
    ]
}
