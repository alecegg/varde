use super::Case;

/// Fixture contracts for Dart class-level and top-level hardcoded-credential
/// rules.
///
/// Dart gives each declaration form its own node kind, so members and top-level
/// declarations take separate rules: untyped `final`/`var` members, untyped
/// `const` and `static final` members, typed members, and typed `const` /
/// `static` members, plus the top-level forms. Member patterns start with
/// `$$$MOD` and are wrapped in a class body, so `static`, `late` and `final`
/// are ignored; top-level patterns end in `;` and parse as written. Raw (`r'...'`)
/// and triple-quoted multiline literals are invalid cases of every Dart rule:
/// the widened shared VAL accepts their delimiters.
pub fn cases() -> Vec<Case> {
    let names = ["api_key", "client_secret", "auth_token"];
    let values = ["9abcdefghijklmno", "abcdefg9hijklmno", "abcdefghijklmno9"];

    // (id, template, valid extras): `{name}`/`{value}` are substituted.
    let forms: [(&'static str, &[&str], &[&str]); 8] = [
        (
            "hardcoded-credential-dart-member",
            &[
                "class C {{ final {name} = \"{value}\"; }}",
                "class C {{ var {name} = \"{value}\"; }}",
            ],
            &[
                "class C { final api_key = getSecret(); }",
                // Typed and `const` members belong to other rules.
                "class C { final String api_key = \"9abcdefghijklmno\"; }",
                "class C { static const api_key = \"9abcdefghijklmno\"; }",
            ],
        ),
        (
            "hardcoded-credential-dart-member-const",
            &[
                "class C {{ static const {name} = \"{value}\"; }}",
                "class C {{ static final {name} = \"{value}\"; }}",
            ],
            &[
                "class C { static const api_key = getSecret(); }",
                "class C { static const String api_key = \"9abcdefghijklmno\"; }",
                "class C { final api_key = \"9abcdefghijklmno\"; }",
            ],
        ),
        (
            "hardcoded-credential-dart-member-typed",
            &[
                "class C {{ final String {name} = \"{value}\"; }}",
                "class C {{ String {name} = \"{value}\"; }}",
                "class C {{ static String {name} = \"{value}\"; }}",
                "class C {{ late final String {name} = \"{value}\"; }}",
            ],
            &[
                "class C { final String api_key = getSecret(); }",
                "class C { static const String api_key = \"9abcdefghijklmno\"; }",
                "class C { final api_key = \"9abcdefghijklmno\"; }",
            ],
        ),
        (
            "hardcoded-credential-dart-member-const-typed",
            &[
                "class C {{ static const String {name} = \"{value}\"; }}",
                "class C {{ static final String {name} = \"{value}\"; }}",
            ],
            &[
                "class C { static const String api_key = getSecret(); }",
                "class C { final String api_key = \"9abcdefghijklmno\"; }",
                "class C { static const api_key = \"9abcdefghijklmno\"; }",
            ],
        ),
        (
            "hardcoded-credential-dart-top-level",
            &["final {name} = \"{value}\";", "const {name} = \"{value}\";"],
            &[
                "final api_key = getSecret();",
                "var api_key = \"9abcdefghijklmno\";",
                "final String api_key = \"9abcdefghijklmno\";",
                "class C { final api_key = \"9abcdefghijklmno\"; }",
            ],
        ),
        (
            "hardcoded-credential-dart-top-level-var",
            &["var {name} = \"{value}\";"],
            &[
                "var api_key = getSecret();",
                "final api_key = \"9abcdefghijklmno\";",
                "String api_key = \"9abcdefghijklmno\";",
            ],
        ),
        (
            "hardcoded-credential-dart-top-level-typed",
            &[
                "String {name} = \"{value}\";",
                "late final String {name} = \"{value}\";",
            ],
            &[
                "String api_key = getSecret();",
                "final String api_key = \"9abcdefghijklmno\";",
                "var api_key = \"9abcdefghijklmno\";",
                "class C { String api_key = \"9abcdefghijklmno\"; }",
            ],
        ),
        (
            "hardcoded-credential-dart-top-level-final-typed",
            &[
                "final String {name} = \"{value}\";",
                "const String {name} = \"{value}\";",
            ],
            &[
                "final String api_key = getSecret();",
                "String api_key = \"9abcdefghijklmno\";",
                "final api_key = \"9abcdefghijklmno\";",
            ],
        ),
    ];

    let mut cases: Vec<Case> = forms
        .into_iter()
        .map(|(id, templates, extra_valid)| {
            let mut invalid = Vec::new();
            let mut valid = Vec::new();
            for template in templates {
                // Templates are written with doubled braces for class bodies.
                let template = template.replace("{{", "{").replace("}}", "}");
                for (name, value) in names.iter().zip(values) {
                    invalid.push(template.replace("{name}", name).replace("{value}", value));
                }
                valid.push(
                    template
                        .replace("{name}", "api_key")
                        .replace("{value}", "9abcdefghijklmn"),
                );
                valid.push(
                    template
                        .replace("{name}", "api_key")
                        .replace("{value}", "abcdefghijklmnop"),
                );
                valid.push(
                    template
                        .replace("{name}", "settings")
                        .replace("{value}", "9abcdefghijklmno"),
                );
            }
            valid.extend(extra_valid.iter().map(|snippet| (*snippet).to_string()));
            Case::new(id, &["dart"], invalid, valid)
        })
        .collect();

    for (id, snippets) in [
        (
            "hardcoded-credential-dart-member",
            &[
                "class C { final api_key = r'9abcdefghijklmno'; }",
                "class C { final api_key = '''\n9abcdefghijklmno\n'''; }",
            ][..],
        ),
        (
            "hardcoded-credential-dart-member-const",
            &["class C { static const api_key = r'9abcdefghijklmno'; }"][..],
        ),
        (
            "hardcoded-credential-dart-member-typed",
            &["class C { final String api_key = r'9abcdefghijklmno'; }"][..],
        ),
        (
            "hardcoded-credential-dart-member-const-typed",
            &["class C { static const String api_key = r'9abcdefghijklmno'; }"][..],
        ),
        (
            "hardcoded-credential-dart-top-level",
            &[
                "final api_key = r'9abcdefghijklmno';",
                "const api_key = '''\n9abcdefghijklmno\n''';",
            ][..],
        ),
        (
            "hardcoded-credential-dart-top-level-var",
            &["var api_key = r'9abcdefghijklmno';"][..],
        ),
        (
            "hardcoded-credential-dart-top-level-typed",
            &["String api_key = r'9abcdefghijklmno';"][..],
        ),
        (
            "hardcoded-credential-dart-top-level-final-typed",
            &["final String api_key = r'9abcdefghijklmno';"][..],
        ),
    ] {
        let case = cases
            .iter_mut()
            .find(|case| case.id == id)
            .unwrap_or_else(|| panic!("no case for {id}"));
        case.invalid
            .extend(snippets.iter().map(|snippet| (*snippet).to_string()));
    }
    cases
}
