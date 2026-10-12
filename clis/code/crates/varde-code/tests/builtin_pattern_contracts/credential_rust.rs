use super::Case;

/// Fixture contracts for rust hardcoded-credential rules.
///
/// Snippets are standalone Rust files, so statement forms sit inside a
/// `fn main()` body; item forms (`const`, `static`) sit at top level.
///
/// invalid: a 16+ character string literal containing a digit bound to a
/// credential-named binding, covering `let`, type-annotated `let`, `const`
/// and `static`.
///
/// valid: the shared family negatives (a short literal, a digit-free literal,
/// a non-credential name, a member/property assignment, an environment or
/// config lookup, tuple destructuring), plus cross-rule negatives (each form
/// is the invalid case for exactly one rule). The `$$$MOD` patterns ignore
/// modifiers, so `let mut`, `pub const`, `pub static` and `static mut` are
/// invalid cases of their rule. Raw string literals (`r"..."`, `r#"..."#`,
/// `b"..."`) are invalid cases: the widened shared VAL accepts their
/// delimiters.
pub fn cases() -> Vec<Case> {
    let values = ["9abcdefghijklmno", "abcdefg9hijklmno", "abcdefghijklmno9"];
    let mut invalid_let: Vec<String> = Vec::new();
    let mut invalid_let_typed: Vec<String> = Vec::new();
    for (name, value) in [
        ("api_key", values[0]),
        ("password", values[1]),
        ("access_token", values[2]),
    ] {
        invalid_let.push(format!("fn main() {{ let {name} = \"{value}\"; }}"));
        invalid_let_typed.push(format!("fn main() {{ let {name}: &str = \"{value}\"; }}"));
    }
    invalid_let.push("fn main() { let client_secret = \"9abcdefghijklmnop\"; }".to_string());
    invalid_let.push("fn main() { let session_token = \"9a8b7c6d5e4f3g2h\"; }".to_string());
    invalid_let.push("fn main() { let token = \"9ab_cd-ef+gh/ij=kl\"; }".to_string());
    invalid_let_typed
        .push("fn main() { let session_token: &str = \"9a8b7c6d5e4f3g2h\"; }".to_string());
    invalid_let.push("fn main() { let mut api_key = \"9abcdefghijklmno\"; }".to_string());
    invalid_let.push("fn main() { let api_key = r\"9abcdefghijklmno\"; }".to_string());
    invalid_let.push("fn main() { let api_key = r#\"9abcdefghijklmno\"#; }".to_string());
    invalid_let.push("fn main() { let api_key = b\"9abcdefghijklmno\"; }".to_string());
    invalid_let_typed
        .push("fn main() { let mut password: &str = \"abcdefg9hijklmno\"; }".to_string());
    invalid_let_typed
        .push("fn main() { let api_key: &str = r#\"9abcdefghijklmno\"#; }".to_string());

    let valid_let = vec![
        // short literal
        "fn main() { let api_key = \"9abcdefghijklmn\"; }".to_string(),
        "fn main() { let api_key = r\"9abcdefghijklmn\"; }".to_string(),
        // 16+ chars but no digit
        "fn main() { let api_key = \"abcdefghijklmnop\"; }".to_string(),
        // non-credential name
        "fn main() { let username = \"9abcdefghijklmno\"; }".to_string(),
        // type-annotated form belongs to the -typed rule
        "fn main() { let api_key: &str = \"9abcdefghijklmno\"; }".to_string(),
        // member/property assignment
        "fn main() { config.api_key = \"9abcdefghijklmno\"; }".to_string(),
        // environment lookup
        "fn main() { let api_key = std::env::var(\"API_KEY\").expect(\"no API key\"); }"
            .to_string(),
        // config lookup via env! is a macro, not a literal
        "fn main() { let api_key = env!(\"API_KEY\"); }".to_string(),
        // tuple destructuring: the KEY capture is the whole pattern
        "fn main() { let (api_key, secret) = (\"9abcdefghijklmno\", \"abcdefg9hijklmno\"); }"
            .to_string(),
        // plain function call value
        "fn main() { let api_key = load_api_key(); }".to_string(),
        "fn main() { let mut api_key = \"9abcdefghijklmn\"; }".to_string(),
        "fn main() { let mut username = \"9abcdefghijklmno\"; }".to_string(),
        // const item form belongs to the -const rule
        "const API_KEY: &str = \"9abcdefghijklmno\";".to_string(),
    ];

    let valid_let_typed = vec![
        "fn main() { let api_key: &str = \"9abcdefghijklmn\"; }".to_string(),
        "fn main() { let api_key: &str = \"abcdefghijklmnop\"; }".to_string(),
        "fn main() { let username: &str = \"9abcdefghijklmno\"; }".to_string(),
        "fn main() { let api_key = \"9abcdefghijklmno\"; }".to_string(),
        "fn main() { config.api_key = \"9abcdefghijklmno\"; }".to_string(),
        "fn main() { let api_key: String = std::env::var(\"API_KEY\").expect(\"no API key\"); }"
            .to_string(),
        "fn main() { let api_key: &str = env!(\"API_KEY\"); }".to_string(),
        "const API_KEY: &str = \"9abcdefghijklmno\";".to_string(),
    ];

    let mut invalid_const: Vec<String> = Vec::new();
    for (name, value) in [
        ("API_KEY", values[0]),
        ("CLIENT_SECRET", values[1]),
        ("ACCESS_TOKEN", values[2]),
    ] {
        invalid_const.push(format!("const {name}: &str = \"{value}\";"));
    }
    invalid_const.push("const PASSWORD: &'static str = \"9a8b7c6d5e4f3g2h\";".to_string());
    invalid_const.push("pub const API_KEY: &str = \"9abcdefghijklmno\";".to_string());
    invalid_const.push("pub(crate) const PASSWORD: &str = \"abcdefg9hijklmno\";".to_string());
    invalid_const.push("const API_KEY: &str = r\"9abcdefghijklmno\";".to_string());
    invalid_const
        .push("fn main() { const SESSION_TOKEN: &str = \"9abcdefghijklmnop\"; }".to_string());

    let valid_const = vec![
        "const API_KEY: &str = \"9abcdefghijklmn\";".to_string(),
        "const API_KEY: &str = \"abcdefghijklmnop\";".to_string(),
        "const USERNAME: &str = \"9abcdefghijklmno\";".to_string(),
        "const API_KEY: &str = env!(\"API_KEY\");".to_string(),
        "const API_KEY: Option<&str> = option_env!(\"API_KEY\");".to_string(),
        "static API_KEY: &str = \"9abcdefghijklmno\";".to_string(),
        "pub const API_KEY: &str = \"9abcdefghijklmn\";".to_string(),
        "pub const USERNAME: &str = \"9abcdefghijklmno\";".to_string(),
        "pub static API_KEY: &str = \"9abcdefghijklmno\";".to_string(),
    ];

    let mut invalid_static: Vec<String> = Vec::new();
    for (name, value) in [
        ("API_KEY", values[0]),
        ("PASSWORD", values[1]),
        ("ACCESS_TOKEN", values[2]),
    ] {
        invalid_static.push(format!("static {name}: &str = \"{value}\";"));
    }
    invalid_static.push("static SESSION_TOKEN: &'static str = \"9a8b7c6d5e4f3g2h\";".to_string());
    invalid_static.push("pub static API_KEY: &str = \"9abcdefghijklmno\";".to_string());
    invalid_static.push("static mut PASSWORD: &str = \"abcdefg9hijklmno\";".to_string());
    invalid_static.push("pub static mut ACCESS_TOKEN: &str = \"abcdefghijklmno9\";".to_string());
    invalid_static.push("static API_KEY: &str = r#\"9abcdefghijklmno\"#;".to_string());

    let valid_static = vec![
        "static API_KEY: &str = \"9abcdefghijklmn\";".to_string(),
        "static API_KEY: &str = \"abcdefghijklmnop\";".to_string(),
        "static USERNAME: &str = \"9abcdefghijklmno\";".to_string(),
        "static API_KEY: &str = env!(\"API_KEY\");".to_string(),
        "const API_KEY: &str = \"9abcdefghijklmno\";".to_string(),
        "pub static API_KEY: &str = \"9abcdefghijklmn\";".to_string(),
        "static mut USERNAME: &str = \"9abcdefghijklmno\";".to_string(),
        "pub const API_KEY: &str = \"9abcdefghijklmno\";".to_string(),
    ];

    vec![
        Case::new(
            "hardcoded-credential-rust",
            &["rust"],
            invalid_let,
            valid_let,
        ),
        Case::new(
            "hardcoded-credential-rust-typed",
            &["rust"],
            invalid_let_typed,
            valid_let_typed,
        ),
        Case::new(
            "hardcoded-credential-rust-const",
            &["rust"],
            invalid_const,
            valid_const,
        ),
        Case::new(
            "hardcoded-credential-rust-static",
            &["rust"],
            invalid_static,
            valid_static,
        ),
    ]
}
