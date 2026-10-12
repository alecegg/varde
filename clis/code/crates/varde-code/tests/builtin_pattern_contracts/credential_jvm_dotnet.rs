use super::Case;

/// Fixture contracts for jvm/dotnet hardcoded-credential rules.
///
/// Each rule covers one declaration form: the matcher locates a pattern by
/// node kind, so Kotlin/Scala `val` and `var`, typed and untyped, cannot share
/// a pattern. The `$$$MOD` rules (Kotlin, Scala, the Java field rule and the
/// C# property rules) ignore modifiers, so `private`, `const`, `override` and
/// `lazy` declarations are invalid cases of their `val`/`var` rule. Java
/// locals and fields are separate node kinds with separate rules; `$TYPE` in
/// the C# declaration pattern absorbs modifiers, so one C# rule covers local,
/// field, `const` and `readonly` declarations. C# auto-property initializers
/// are property declarations, one rule per accessor list.
///
/// Raw and multiline literals are invalid cases wherever the language has one:
/// Java/Kotlin/Scala text blocks (`"""..."""`), C# verbatim (`@"..."`) and
/// raw (`"""..."""`) strings. Interpolated forms (Kotlin/Scala `"abc${x}..."`,
/// C# `$@"..."`) stay valid: the shared VAL rejects their brace/dollar content.
pub fn cases() -> Vec<Case> {
    let java = Case::new(
        "hardcoded-credential-java",
        &["java"],
        strings(&[
            "class C { void m() { String api_key = \"9abcdefghijklmno\"; } }",
            "class C { void m() { String client_secret = \"abcdefg9hijklmno\"; } }",
            "class C { void m() { var auth_token = \"abcdefghijklmno9\"; } }",
            "class C { void m() { String password = \"9abcdefghijklmno\"; } }",
            "class C { void m() { String api_key = \"\"\"\n9abcdefghijklmno\n\"\"\"; } }",
        ]),
        strings(&[
            "class C { void m() { String api_key = \"9abcdefghijklmn\"; } }",
            "class C { void m() { String api_key = \"abcdefghijklmnop\"; } }",
            "class C { void m() { String other = \"9abcdefghijklmno\"; } }",
            "class C { void m() { config.api_key = \"9abcdefghijklmno\"; } }",
            "class C { void m() { String api_key = System.getenv(\"API_KEY\"); } }",
        ]),
    );

    let java_field = Case::new(
        "hardcoded-credential-java-field",
        &["java"],
        strings(&[
            "class C { private static final String API_KEY = \"9abcdefghijklmno\"; }",
            "class C { String client_secret = \"abcdefg9hijklmno\"; }",
            "class C { public final String auth_token = \"abcdefghijklmno9\"; }",
            "class C { static String password = \"9abcdefghijklmno\"; }",
            "class C { String api_key = \"\"\"\n9abcdefghijklmno\n\"\"\"; }",
        ]),
        strings(&[
            "class C { String api_key = \"9abcdefghijklmn\"; }",
            "class C { String api_key = \"abcdefghijklmnop\"; }",
            "class C { String other = \"9abcdefghijklmno\"; }",
            "class C { String api_key = System.getenv(\"API_KEY\"); }",
            // A local declaration belongs to the local rule.
            "class C { void m() { String api_key = \"9abcdefghijklmno\"; } }",
        ]),
    );

    let kotlin_val = Case::new(
        "hardcoded-credential-kotlin",
        &["kotlin"],
        strings(&[
            "fun m() { val api_key = \"9abcdefghijklmno\" }",
            "fun m() { val client_secret = \"abcdefg9hijklmno\" }",
            "fun m() { val auth_token = \"abcdefghijklmno9\" }",
            "fun m() { val password = \"9abcdefghijklmno\" }",
            "class C { private val api_key = \"9abcdefghijklmno\"; }",
            "class C { override val client_secret = \"abcdefg9hijklmno\"; }",
            "const val auth_token = \"abcdefghijklmno9\"",
            "private const val password = \"9abcdefghijklmno\"",
            "class C {\n  companion object {\n    private const val api_key = \"9abcdefghijklmno\"\n  }\n}",
            "fun m() { val api_key = \"\"\"\n9abcdefghijklmno\n\"\"\" }",
        ]),
        strings(&[
            "class C { private val api_key = \"9abcdefghijklmn\"; }",
            "val api_key: String = \"9abcdefghijklmno\"",
            "fun m() { val api_key = \"9abcdefghijklmn\" }",
            "fun m() { val api_key = \"abcdefghijklmnop\" }",
            "fun m() { val other = \"9abcdefghijklmno\" }",
            "fun m() { config.api_key = \"9abcdefghijklmno\" }",
            "fun m() { val api_key = System.getenv(\"API_KEY\") }",
            "fun m() { val api_key = \"abc${secret}9abcdefghijklmno\" }",
        ]),
    );

    let kotlin_var = Case::new(
        "hardcoded-credential-kotlin-var",
        &["kotlin"],
        strings(&[
            "fun m() { var api_key = \"9abcdefghijklmno\" }",
            "fun m() { var client_secret = \"abcdefg9hijklmno\" }",
            "fun m() { var auth_token = \"abcdefghijklmno9\" }",
            "class C { private var password = \"9abcdefghijklmno\"; }",
        ]),
        strings(&[
            "fun m() { var api_key = \"9abcdefghijklmn\" }",
            "fun m() { var api_key = \"abcdefghijklmnop\" }",
            "fun m() { var other = \"9abcdefghijklmno\" }",
            "fun m() { config.api_key = \"9abcdefghijklmno\" }",
            "fun m() { var api_key = System.getenv(\"API_KEY\") }",
            "var api_key: String = \"9abcdefghijklmno\"",
        ]),
    );

    let kotlin_typed = Case::new(
        "hardcoded-credential-kotlin-typed",
        &["kotlin"],
        strings(&[
            "val api_key: String = \"9abcdefghijklmno\"",
            "class C { private val client_secret: String = \"abcdefg9hijklmno\"; }",
            "const val auth_token: String = \"abcdefghijklmno9\"",
            "fun m() { val password: String = \"9abcdefghijklmno\" }",
            "val api_key: String = \"\"\"\n9abcdefghijklmno\n\"\"\"",
        ]),
        strings(&[
            "val api_key: String = \"9abcdefghijklmn\"",
            "val api_key: String = \"abcdefghijklmnop\"",
            "val other: String = \"9abcdefghijklmno\"",
            "val api_key: String = System.getenv(\"API_KEY\")",
            // The untyped form belongs to the untyped rule.
            "val api_key = \"9abcdefghijklmno\"",
        ]),
    );

    let kotlin_var_typed = Case::new(
        "hardcoded-credential-kotlin-var-typed",
        &["kotlin"],
        strings(&[
            "var api_key: String = \"9abcdefghijklmno\"",
            "class C { private var client_secret: String = \"abcdefg9hijklmno\"; }",
            "fun m() { var auth_token: String = \"abcdefghijklmno9\" }",
        ]),
        strings(&[
            "var api_key: String = \"9abcdefghijklmn\"",
            "var api_key: String = \"abcdefghijklmnop\"",
            "var other: String = \"9abcdefghijklmno\"",
            "var api_key: String = System.getenv(\"API_KEY\")",
            "var api_key = \"9abcdefghijklmno\"",
        ]),
    );

    let scala_val = Case::new(
        "hardcoded-credential-scala",
        &["scala"],
        strings(&[
            "class C { val api_key = \"9abcdefghijklmno\" }",
            "class C { val client_secret = \"abcdefg9hijklmno\" }",
            "class C { def m() = { val auth_token = \"abcdefghijklmno9\" } }",
            "class C { val password = \"9abcdefghijklmno\" }",
            "class C { private val api_key = \"9abcdefghijklmno\" }",
            "class C { final val client_secret = \"abcdefg9hijklmno\" }",
            "class C { lazy val auth_token = \"abcdefghijklmno9\" }",
            "class C { protected[this] val password = \"9abcdefghijklmno\" }",
            "class C { val api_key = \"\"\"\n9abcdefghijklmno\n\"\"\" }",
        ]),
        strings(&[
            "class C { val api_key = \"9abcdefghijklmn\" }",
            "class C { val api_key = \"abcdefghijklmnop\" }",
            "class C { val other = \"9abcdefghijklmno\" }",
            "class C { def m() = { config.api_key = \"9abcdefghijklmno\" } }",
            "class C { val api_key = sys.env(\"API_KEY\") }",
            "class C { val api_key: String = \"9abcdefghijklmno\" }",
            "class C { val api_key = s\"abc${secret}9abcdefghijklmno\" }",
        ]),
    );

    let scala_typed = Case::new(
        "hardcoded-credential-scala-typed",
        &["scala"],
        strings(&[
            "class C { val api_key: String = \"9abcdefghijklmno\" }",
            "class C { private final val client_secret: String = \"abcdefg9hijklmno\" }",
            "class C { def m() = { val auth_token: String = \"abcdefghijklmno9\" } }",
            "class C { val api_key: String = \"\"\"\n9abcdefghijklmno\n\"\"\" }",
        ]),
        strings(&[
            "class C { val api_key: String = \"9abcdefghijklmn\" }",
            "class C { val api_key: String = \"abcdefghijklmnop\" }",
            "class C { val other: String = \"9abcdefghijklmno\" }",
            "class C { val api_key: String = sys.env(\"API_KEY\") }",
            "class C { val api_key = \"9abcdefghijklmno\" }",
        ]),
    );

    let scala_var = Case::new(
        "hardcoded-credential-scala-var",
        &["scala"],
        strings(&[
            "class C { var api_key = \"9abcdefghijklmno\" }",
            "class C { def m() = { var client_secret = \"abcdefg9hijklmno\" } }",
            "class C { var auth_token = \"abcdefghijklmno9\" }",
        ]),
        strings(&[
            "class C { var api_key = \"9abcdefghijklmn\" }",
            "class C { var api_key = \"abcdefghijklmnop\" }",
            "class C { var other = \"9abcdefghijklmno\" }",
            "class C { def m() = { config.api_key = \"9abcdefghijklmno\" } }",
            "class C { var api_key = sys.env(\"API_KEY\") }",
            "class C { var api_key: String = \"9abcdefghijklmno\" }",
        ]),
    );

    let scala_var_typed = Case::new(
        "hardcoded-credential-scala-var-typed",
        &["scala"],
        strings(&[
            "class C { var api_key: String = \"9abcdefghijklmno\" }",
            "class C { private var client_secret: String = \"abcdefg9hijklmno\" }",
            "class C { def m() = { var auth_token: String = \"abcdefghijklmno9\" } }",
        ]),
        strings(&[
            "class C { var api_key: String = \"9abcdefghijklmn\" }",
            "class C { var api_key: String = \"abcdefghijklmnop\" }",
            "class C { var other: String = \"9abcdefghijklmno\" }",
            "class C { var api_key: String = sys.env(\"API_KEY\") }",
            "class C { var api_key = \"9abcdefghijklmno\" }",
        ]),
    );

    let csharp = Case::new(
        "hardcoded-credential-csharp",
        &["csharp"],
        strings(&[
            "class C { void M() { string api_key = \"9abcdefghijklmno\"; } }",
            "class C { private readonly string client_secret = \"abcdefg9hijklmno\"; }",
            "class C { const string auth_token = \"abcdefghijklmno9\"; }",
            "class C { string password = \"9abcdefghijklmno\"; }",
            "class C { string api_key = @\"9abcdefghijklmno\"; }",
            "class C { string api_key = \"\"\"9abcdefghijklmno\"\"\"; }",
        ]),
        strings(&[
            "class C { void M() { string api_key = \"9abcdefghijklmn\"; } }",
            "class C { string api_key = \"abcdefghijklmnop\"; }",
            "class C { string other = \"9abcdefghijklmno\"; }",
            "class C { void M() { config.api_key = \"9abcdefghijklmno\"; } }",
            "class C { void M() { string api_key = Environment.GetEnvironmentVariable(\"API_KEY\"); } }",
        ]),
    );

    let mut cases = vec![
        java,
        java_field,
        kotlin_val,
        kotlin_typed,
        kotlin_var,
        kotlin_var_typed,
        scala_val,
        scala_typed,
        scala_var,
        scala_var_typed,
        csharp,
    ];

    for (id, accessors) in [
        ("hardcoded-credential-csharp-property", "get; set;"),
        ("hardcoded-credential-csharp-property-get", "get;"),
        ("hardcoded-credential-csharp-property-init", "get; init;"),
    ] {
        let property = |name: &str, value: &str| {
            format!("class C {{ public string {name} {{ {accessors} }} = \"{value}\"; }}")
        };
        cases.push(Case::new(
            id,
            &["csharp"],
            vec![
                property("ApiKey", "9abcdefghijklmno"),
                property("client_secret", "abcdefg9hijklmno"),
                format!(
                    "class C {{ internal static string Password {{ {accessors} }} = \"abcdefghijklmno9\"; }}"
                ),
            ],
            vec![
                property("ApiKey", "9abcdefghijklmn"),
                property("ApiKey", "abcdefghijklmnop"),
                property("Other", "9abcdefghijklmno"),
                format!(
                    "class C {{ public string ApiKey {{ {accessors} }} = Environment.GetEnvironmentVariable(\"API_KEY\"); }}"
                ),
                format!(
                    "class C {{ public string ApiKey {{ {accessors} }} = $@\"abc{{secret}}9abcdefghijklmno\"; }}"
                ),
                // A field belongs to the declaration rule.
                "class C { public string ApiKey = \"9abcdefghijklmno\"; }".to_string(),
            ],
        ));
    }
    cases
}

fn strings(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}
