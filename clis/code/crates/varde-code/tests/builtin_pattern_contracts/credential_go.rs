use super::Case;

/// Fixture contracts for Go hardcoded-credential rules.
///
/// Go binds string literals to credential-named identifiers in four syntactic
/// forms, each its own tree-sitter node kind: `:=` (short_var_declaration),
/// `=` (assignment_statement), `var` (var_declaration) and `const`
/// (const_declaration). One rule covers one form; every rule shares the same
/// KEY and VAL constraints as `hardcoded-credential-literal`. The `var`
/// rule's `$$$T` slot matches zero or one type node, so typed
/// `var x string = ".."` and untyped `var x = ".."` declarations share one
/// rule.
///
/// invalid: a 16-character string literal containing a digit (the shared VAL
/// constraint is 16+ allowed characters AND at least one digit) bound to a
/// credential-named identifier, covering every form and typed var.
///
/// valid: a short literal (15 characters), a 16-character literal without a
/// digit, a non-credential name, a member/property assignment (the KEY
/// capture binds the selector expression, whose text fails the anchored KEY
/// regex), an environment or config lookup on the right-hand side (the VAL
/// capture is not a string literal), and multi-name bindings (the left side
/// is an identifier list). Raw backtick literals, including multiline ones, are
/// invalid cases: the widened shared VAL accepts the backtick delimiter.
/// Remaining limit: multi-name bindings. Every fixture parses as Go; statement
/// forms live inside `func main()`.
pub fn cases() -> Vec<Case> {
    let short_var =
        |name: &str| format!("package p\nfunc main() {{ {name} := \"9abcdefghijklmn\" }}");
    let assign = |name: &str| format!("package p\nfunc main() {{ {name} = \"9abcdefghijklmn\" }}");
    let var_decl = |name: &str| format!("package p\nvar {name} = \"9abcdefghijklmn\"");
    let const_decl = |name: &str| format!("package p\nconst {name} = \"9abcdefghijklmn\"");
    vec![
        Case::new(
            "hardcoded-credential-go",
            &["go"],
            vec![
                "package p\nfunc main() { api_key = \"9abcdefghijklmno\" }".to_string(),
                "package p\nfunc main() { password = \"abcdefghijklmno9\" }".to_string(),
                "package p\nfunc main() { token = \"abcdefg9hijklmno\" }".to_string(),
                "package p\nfunc main() { api_key = `9abcdefghijklmno` }".to_string(),
            ],
            vec![
                assign("api_key"),
                "package p\nfunc main() { api_key = \"abcdefghijklmnop\" }".to_string(),
                "package p\nfunc main() { user_name = \"9abcdefghijklmno\" }".to_string(),
                "package p\nfunc main() { config.APIKey = \"9abcdefghijklmno\" }".to_string(),
                "package p\nfunc main() { api_key = os.Getenv(\"API_KEY\") }".to_string(),
                "package p\nfunc main() { api_key += \"9abcdefghijklmno\" }".to_string(),
                "package p\nfunc main() { apiKey, secret = \"9abcdefghijklmno\", \"abcdefg9hijklmno\" }"
                    .to_string(),
            ],
        ),
        Case::new(
            "hardcoded-credential-go-short-var",
            &["go"],
            vec![
                "package p\nfunc main() { apiKey := \"9abcdefghijklmno\" }".to_string(),
                "package p\nfunc main() { secret := \"abcdefghijklmno9\" }".to_string(),
                "package p\nfunc main() { authToken := \"abcdefg9hijklmno\" }".to_string(),
                "package p\nfunc main() { apiKey := `9abcdefghijklmno` }".to_string(),
            ],
            vec![
                short_var("apiKey"),
                "package p\nfunc main() { apiKey := \"abcdefghijklmnop\" }".to_string(),
                "package p\nfunc main() { count := \"9abcdefghijklmno\" }".to_string(),
                "package p\nfunc main() { apiKey := config.APIKey }".to_string(),
                "package p\nfunc main() { apiKey := os.Getenv(\"API_KEY\") }".to_string(),
                "package p\nfunc main() { for apiKey := range keys {} }".to_string(),
                "package p\nfunc main() { apiKey, err := getCreds() }".to_string(),
            ],
        ),
        Case::new(
            "hardcoded-credential-go-var",
            &["go"],
            vec![
                "package p\nvar apiKey = \"9abcdefghijklmno\"".to_string(),
                "package p\nvar password = \"abcdefghijklmno9\"".to_string(),
                "package p\nvar sessionToken = \"abcdefg9hijklmno\"".to_string(),
                "package p\nvar apiKey = `9abcdefghijklmno`".to_string(),
                "package p\nvar apiKey = `\n9abcdefghijklmno\n`".to_string(),
                "package p\nvar apiKey string = \"9abcdefghijklmno\"".to_string(),
                "package p\nvar password Secret = \"abcdefg9hijklmno\"".to_string(),
            ],
            vec![
                var_decl("apiKey"),
                "package p\nvar apiKey = \"abcdefghijklmnop\"".to_string(),
                "package p\nvar userName = \"9abcdefghijklmno\"".to_string(),
                "package p\nvar apiKey = os.Getenv(\"API_KEY\")".to_string(),
                "package p\nvar apiKey string = \"9abcdefghijklmn\"".to_string(),
                "package p\nvar apiKey string = \"abcdefghijklmnop\"".to_string(),
                "package p\nvar apiKey string = os.Getenv(\"API_KEY\")".to_string(),
                "package p\nvar count int = 9".to_string(),
                "package p\nvar apiKey *string = nil".to_string(),
                "package p\nvar apiKey, password = \"9abcdefghijklmno\", \"abcdefg9hijklmno\""
                    .to_string(),
            ],
        ),
        Case::new(
            "hardcoded-credential-go-const",
            &["go"],
            vec![
                "package p\nconst apiKey = \"9abcdefghijklmno\"".to_string(),
                "package p\nconst clientSecret = \"abcdefghijklmno9\"".to_string(),
                "package p\nconst refreshToken = \"abcdefg9hijklmno\"".to_string(),
                "package p\nconst apiKey = `9abcdefghijklmno`".to_string(),
            ],
            vec![
                const_decl("apiKey"),
                "package p\nconst apiKey = \"abcdefghijklmnop\"".to_string(),
                "package p\nconst width = \"9abcdefghijklmno\"".to_string(),
                "package p\nconst apiKey = config.APIKey".to_string(),
                "package p\nconst apiKey = os.Getenv(\"API_KEY\")".to_string(),
            ],
        ),
    ]
}
