use super::Case;

/// Fixture contracts for native/Apple hardcoded-credential rules.
///
/// Each rule covers one declaration or assignment form: the matcher locates a
/// pattern by node kind, so C/C++ pointer, array and `std::string` declarators
/// and plain assignment cannot share a single pattern. C, C++ and Dart
/// fixtures are function-local (C top-level statements do not parse); Dart
/// class-level and top-level declarations have their own pack and contract.
/// Swift fixtures use struct bodies, top-level declarations and function
/// locals.
///
/// The Swift and C/C++ declaration patterns start with `$$$MOD`, which ignores
/// modifiers: `static`/`private`/`public`/`open` stacks and C/C++ storage
/// classes are invalid cases of the base rule (`also_invalid`). C/C++ sized
/// arrays and the C++ `auto`/`const auto`/`constexpr auto` forms keep their own
/// rules. Remaining reach limits, covered by no rule: C++ types beyond the
/// listed forms and in-class member initializers. Raw and multiline literals
/// are accepted by the widened shared VAL and are pinned as invalid cases on
/// the base rules.
pub fn cases() -> Vec<Case> {
    let c_assignment = Case::new(
        "hardcoded-credential-c",
        &["c"],
        strings(&[
            "void f(void) { api_key = \"9abcdefghijklmno\"; }",
            "void f(void) { client_secret = \"abcdefg9hijklmno\"; }",
            "void f(void) { auth_token = \"abcdefghijklmno9\"; }",
            "void f(void) { password = \"9abcdefghijklmno\"; }",
        ]),
        strings(&[
            "void f(void) { api_key = \"9abcdefghijklmn\"; }",
            "void f(void) { api_key = \"abcdefghijklmnop\"; }",
            "void f(void) { settings = \"9abcdefghijklmno\"; }",
            "void f(void) { config.api_key = \"9abcdefghijklmno\"; }",
            "void f(void) { api_key = getenv(\"API_KEY\"); }",
        ]),
    );

    let c_const_ptr = Case::new(
        "hardcoded-credential-c-const-ptr",
        &["c"],
        strings(&[
            "const char *api_key = \"9abcdefghijklmno\";",
            "const char *client_secret = \"abcdefg9hijklmno\";",
            "const char* auth_token = \"abcdefghijklmno9\";",
            "const char *password = \"9abcdefghijklmno\";",
        ]),
        strings(&[
            "const char *api_key = \"9abcdefghijklmn\";",
            "const char *api_key = \"abcdefghijklmnop\";",
            "const char *settings = \"9abcdefghijklmno\";",
            "config.api_key = \"9abcdefghijklmno\";",
            "const char *api_key = getenv(\"API_KEY\");",
            // Escaped-newline content is outside the shared VAL content class.
            "const char *api_key = \"line1\\n9abcdefghijklmno\";",
        ]),
    );

    let c_ptr = Case::new(
        "hardcoded-credential-c-ptr",
        &["c"],
        strings(&[
            "char *api_key = \"9abcdefghijklmno\";",
            "char *client_secret = \"abcdefg9hijklmno\";",
            "char * auth_token = \"abcdefghijklmno9\";",
        ]),
        strings(&[
            "char *api_key = \"9abcdefghijklmn\";",
            "char *api_key = \"abcdefghijklmnop\";",
            "char *settings = \"9abcdefghijklmno\";",
            "config.api_key = \"9abcdefghijklmno\";",
            "char *api_key = getenv(\"API_KEY\");",
        ]),
    );

    let c_const_array = Case::new(
        "hardcoded-credential-c-const-array",
        &["c"],
        strings(&[
            "const char api_key[] = \"9abcdefghijklmno\";",
            "const char client_secret[] = \"abcdefg9hijklmno\";",
            "const char auth_token[] = \"abcdefghijklmno9\";",
        ]),
        strings(&[
            "const char api_key[] = \"9abcdefghijklmn\";",
            "const char api_key[] = \"abcdefghijklmnop\";",
            "const char settings[] = \"9abcdefghijklmno\";",
            "config.api_key = \"9abcdefghijklmno\";",
            "const char api_key[] = \"\";",
        ]),
    );

    let c_array = Case::new(
        "hardcoded-credential-c-array",
        &["c"],
        strings(&[
            "char api_key[] = \"9abcdefghijklmno\";",
            "char client_secret[] = \"abcdefg9hijklmno\";",
            "char auth_token[] = \"abcdefghijklmno9\";",
        ]),
        strings(&[
            "char api_key[] = \"9abcdefghijklmn\";",
            "char api_key[] = \"abcdefghijklmnop\";",
            "char settings[] = \"9abcdefghijklmno\";",
            "config.api_key = \"9abcdefghijklmno\";",
            "char api_key[] = \"\";",
        ]),
    );

    let cpp_assignment = Case::new(
        "hardcoded-credential-cpp",
        &["cpp"],
        strings(&[
            "void f() { api_key = \"9abcdefghijklmno\"; }",
            "void f() { client_secret = \"abcdefg9hijklmno\"; }",
            "void f() { auth_token = \"abcdefghijklmno9\"; }",
            "void f() { password = \"9abcdefghijklmno\"; }",
        ]),
        strings(&[
            "void f() { api_key = \"9abcdefghijklmn\"; }",
            "void f() { api_key = \"abcdefghijklmnop\"; }",
            "void f() { settings = \"9abcdefghijklmno\"; }",
            "void f() { config.api_key = \"9abcdefghijklmno\"; }",
            "void f() { api_key = std::getenv(\"API_KEY\"); }",
        ]),
    );

    let cpp_const_ptr = Case::new(
        "hardcoded-credential-cpp-const-ptr",
        &["cpp"],
        strings(&[
            "const char *api_key = \"9abcdefghijklmno\";",
            "const char *client_secret = \"abcdefg9hijklmno\";",
            "const char* auth_token = \"abcdefghijklmno9\";",
            "void f() { const char *password = \"9abcdefghijklmno\"; }",
            "const char *api_key = R\"(9abcdefghijklmno)\";",
        ]),
        strings(&[
            "const char *api_key = \"9abcdefghijklmn\";",
            "const char *api_key = \"abcdefghijklmnop\";",
            "const char *settings = \"9abcdefghijklmno\";",
            "config.api_key = \"9abcdefghijklmno\";",
            "const char *api_key = std::getenv(\"API_KEY\");",
        ]),
    );

    let cpp_ptr = Case::new(
        "hardcoded-credential-cpp-ptr",
        &["cpp"],
        strings(&[
            "char *api_key = \"9abcdefghijklmno\";",
            "char *client_secret = \"abcdefg9hijklmno\";",
            "char * auth_token = \"abcdefghijklmno9\";",
        ]),
        strings(&[
            "char *api_key = \"9abcdefghijklmn\";",
            "char *api_key = \"abcdefghijklmnop\";",
            "char *settings = \"9abcdefghijklmno\";",
            "config.api_key = \"9abcdefghijklmno\";",
            "char *api_key = std::getenv(\"API_KEY\");",
        ]),
    );

    let cpp_string = Case::new(
        "hardcoded-credential-cpp-string",
        &["cpp"],
        strings(&[
            "std::string api_key = \"9abcdefghijklmno\";",
            "std::string client_secret = \"abcdefg9hijklmno\";",
            "void f() { std::string auth_token = \"abcdefghijklmno9\"; }",
            "std::string password = \"9abcdefghijklmno\";",
        ]),
        strings(&[
            "std::string api_key = \"9abcdefghijklmn\";",
            "std::string api_key = \"abcdefghijklmnop\";",
            "std::string settings = \"9abcdefghijklmno\";",
            "config.api_key = \"9abcdefghijklmno\";",
            "std::string api_key = std::getenv(\"API_KEY\");",
        ]),
    );

    let cpp_const_string = Case::new(
        "hardcoded-credential-cpp-const-string",
        &["cpp"],
        strings(&[
            "const std::string api_key = \"9abcdefghijklmno\";",
            "const std::string client_secret = \"abcdefg9hijklmno\";",
            "void f() { const std::string auth_token = \"abcdefghijklmno9\"; }",
        ]),
        strings(&[
            "const std::string api_key = \"9abcdefghijklmn\";",
            "const std::string api_key = \"abcdefghijklmnop\";",
            "const std::string settings = \"9abcdefghijklmno\";",
            "config.api_key = \"9abcdefghijklmno\";",
            "const std::string api_key = std::getenv(\"API_KEY\");",
        ]),
    );

    let swift_assignment = Case::new(
        "hardcoded-credential-swift",
        &["swift"],
        strings(&[
            "func f() { api_key = \"9abcdefghijklmno\" }",
            "func f() { client_secret = \"abcdefg9hijklmno\" }",
            "func f() { auth_token = \"abcdefghijklmno9\" }",
            "func f() { password = \"9abcdefghijklmno\" }",
        ]),
        strings(&[
            "func f() { api_key = \"9abcdefghijklmn\" }",
            "func f() { api_key = \"abcdefghijklmnop\" }",
            "func f() { settings = \"9abcdefghijklmno\" }",
            "func f() { user.password = \"9abcdefghijklmno\" }",
            "func f() { api_key = ProcessInfo.processInfo.environment[\"API_KEY\"] }",
        ]),
    );

    let swift_let = Case::new(
        "hardcoded-credential-swift-let",
        &["swift"],
        strings(&[
            "let api_key = \"9abcdefghijklmno\"",
            "let client_secret = \"abcdefg9hijklmno\"",
            "func f() { let auth_token = \"abcdefghijklmno9\" }",
            "let password = \"9abcdefghijklmno\"",
        ]),
        strings(&[
            "let api_key = \"9abcdefghijklmn\"",
            "let api_key = \"abcdefghijklmnop\"",
            "let settings = \"9abcdefghijklmno\"",
            "user.password = \"9abcdefghijklmno\"",
            "let api_key = ProcessInfo.processInfo.environment[\"API_KEY\"]",
            "let api_key = \"abc\\(secret)9abcdefghijklmno\"",
        ]),
    );

    let swift_var = Case::new(
        "hardcoded-credential-swift-var",
        &["swift"],
        strings(&[
            "var api_key = \"9abcdefghijklmno\"",
            "var client_secret = \"abcdefg9hijklmno\"",
            "func f() { var auth_token = \"abcdefghijklmno9\" }",
        ]),
        strings(&[
            "var api_key = \"9abcdefghijklmn\"",
            "var api_key = \"abcdefghijklmnop\"",
            "var settings = \"9abcdefghijklmno\"",
            "user.password = \"9abcdefghijklmno\"",
            "var api_key = ProcessInfo.processInfo.environment[\"API_KEY\"]",
        ]),
    );

    let swift_typed_let = Case::new(
        "hardcoded-credential-swift-typed-let",
        &["swift"],
        strings(&[
            "let api_key: String = \"9abcdefghijklmno\"",
            "let client_secret: String = \"abcdefg9hijklmno\"",
            "func f() { let auth_token: String = \"abcdefghijklmno9\" }",
        ]),
        strings(&[
            "let api_key: String = \"9abcdefghijklmn\"",
            "let api_key: String = \"abcdefghijklmnop\"",
            "let settings: String = \"9abcdefghijklmno\"",
            "user.password = \"9abcdefghijklmno\"",
            "let api_key: String = ProcessInfo.processInfo.environment[\"API_KEY\"]",
        ]),
    );

    let swift_typed_var = Case::new(
        "hardcoded-credential-swift-typed-var",
        &["swift"],
        strings(&[
            "var api_key: String = \"9abcdefghijklmno\"",
            "var client_secret: String = \"abcdefg9hijklmno\"",
            "func f() { var auth_token: String = \"abcdefghijklmno9\" }",
        ]),
        strings(&[
            "var api_key: String = \"9abcdefghijklmn\"",
            "var api_key: String = \"abcdefghijklmnop\"",
            "var settings: String = \"9abcdefghijklmno\"",
            "user.password = \"9abcdefghijklmno\"",
            "var api_key: String = ProcessInfo.processInfo.environment[\"API_KEY\"]",
        ]),
    );

    let dart_assignment = Case::new(
        "hardcoded-credential-dart",
        &["dart"],
        strings(&[
            "void f() { api_key = \"9abcdefghijklmno\"; }",
            "void f() { client_secret = \"abcdefg9hijklmno\"; }",
            "void f() { auth_token = \"abcdefghijklmno9\"; }",
        ]),
        strings(&[
            "void f() { api_key = \"9abcdefghijklmn\"; }",
            "void f() { api_key = \"abcdefghijklmnop\"; }",
            "void f() { settings = \"9abcdefghijklmno\"; }",
            "void f() { user.password = \"9abcdefghijklmno\"; }",
            "void f() { api_key = Platform.environment['API_KEY']!; }",
        ]),
    );

    let dart_declaration = Case::new(
        "hardcoded-credential-dart-declaration",
        &["dart"],
        strings(&[
            "void f() { var api_key = \"9abcdefghijklmno\"; }",
            "void f() { final client_secret = \"abcdefg9hijklmno\"; }",
            "void f() { const auth_token = \"abcdefghijklmno9\"; }",
            "void f() { late final password = \"9abcdefghijklmno\"; }",
        ]),
        strings(&[
            "void f() { var api_key = \"9abcdefghijklmn\"; }",
            "void f() { var api_key = \"abcdefghijklmnop\"; }",
            "void f() { var settings = \"9abcdefghijklmno\"; }",
            "void f() { user.password = \"9abcdefghijklmno\"; }",
            "void f() { final api_key = Platform.environment['API_KEY']!; }",
        ]),
    );

    let dart_typed = Case::new(
        "hardcoded-credential-dart-typed",
        &["dart"],
        strings(&[
            "void f() { String api_key = \"9abcdefghijklmno\"; }",
            "void f() { final String client_secret = \"abcdefg9hijklmno\"; }",
            "void f() { String auth_token = \"abcdefghijklmno9\"; }",
        ]),
        strings(&[
            "void f() { String api_key = \"9abcdefghijklmn\"; }",
            "void f() { String api_key = \"abcdefghijklmnop\"; }",
            "void f() { String settings = \"9abcdefghijklmno\"; }",
            "void f() { user.password = \"9abcdefghijklmno\"; }",
            "void f() { String api_key = Platform.environment['API_KEY']!; }",
        ]),
    );

    let mut cases = vec![
        c_assignment,
        c_const_ptr,
        c_ptr,
        c_const_array,
        c_array,
        cpp_assignment,
        cpp_const_ptr,
        cpp_ptr,
        cpp_string,
        cpp_const_string,
        swift_assignment,
        swift_let,
        swift_var,
        swift_typed_let,
        swift_typed_var,
        dart_assignment,
        dart_declaration,
        dart_typed,
    ];

    for (id, template, env_lookup, other_form) in [
        (
            "hardcoded-credential-c-sized-array",
            "char {name}[64] = \"{value}\";",
            "char api_key[64] = {0};",
            "char api_key[64];",
        ),
        (
            "hardcoded-credential-c-const-sized-array",
            "const char {name}[64] = \"{value}\";",
            "const char api_key[64] = {0};",
            "const char api_key[64];",
        ),
    ] {
        cases.push(form_case(id, C_LANG, template, &[env_lookup, other_form]));
    }

    for (id, template, env_lookup, other_form) in [
        (
            "hardcoded-credential-cpp-const-array",
            "const char {name}[] = \"{value}\";",
            "const char api_key[] = {};",
            "const char api_key[] = \"\";",
        ),
        (
            "hardcoded-credential-cpp-sized-array",
            "char {name}[64] = \"{value}\";",
            "char api_key[64] = {0};",
            "char api_key[64]{};",
        ),
        (
            "hardcoded-credential-cpp-const-sized-array",
            "const char {name}[64] = \"{value}\";",
            "const char api_key[64] = {0};",
            "const char api_key[64]{};",
        ),
        (
            "hardcoded-credential-cpp-constexpr-auto",
            "constexpr auto {name} = \"{value}\";",
            "constexpr auto api_key = std::getenv(\"API_KEY\");",
            "constexpr auto api_key = value;",
        ),
        (
            "hardcoded-credential-cpp-const-auto",
            "const auto {name} = \"{value}\";",
            "const auto api_key = std::getenv(\"API_KEY\");",
            "const auto api_key = value;",
        ),
        (
            "hardcoded-credential-cpp-auto",
            "auto {name} = \"{value}\";",
            "auto api_key = std::getenv(\"API_KEY\");",
            "auto api_key = value;",
        ),
    ] {
        cases.push(form_case(id, CPP_LANG, template, &[env_lookup, other_form]));
    }
    // `$$$MOD` ignores modifiers: stacks of them are invalid cases of the base
    // Swift and C/C++ rules, which is why no per-modifier rule exists.
    also_invalid(
        &mut cases,
        "hardcoded-credential-swift-let",
        &[
            "struct S { private let api_key = \"9abcdefghijklmno\" }",
            "struct S { static let client_secret = \"abcdefg9hijklmno\" }",
            "struct S { private static let auth_token = \"abcdefghijklmno9\" }",
            "public let password = \"9abcdefghijklmno\"",
        ],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-swift-var",
        &[
            "struct S { private var api_key = \"9abcdefghijklmno\" }",
            "class S { public static var client_secret = \"abcdefg9hijklmno\" }",
            "open var auth_token = \"abcdefghijklmno9\"",
        ],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-swift-typed-let",
        &[
            "struct S { private static let api_key: String = \"9abcdefghijklmno\" }",
            "struct S { fileprivate let client_secret: String = \"abcdefg9hijklmno\" }",
        ],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-swift-typed-var",
        &[
            "struct S { internal var api_key: String = \"9abcdefghijklmno\" }",
            "class S { public static var client_secret: String = \"abcdefg9hijklmno\" }",
        ],
    );
    // Widened shared VAL: raw and multiline literals are invalid cases of the
    // base rules.
    also_invalid(
        &mut cases,
        "hardcoded-credential-swift-let",
        &[
            "let api_key = #\"9abcdefghijklmno\"#",
            "let api_key = \"\"\"\n9abcdefghijklmno\n\"\"\"",
        ],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-swift-var",
        &["var api_key = ##\"9abcdefghijklmno\"##"],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-swift-typed-let",
        &["let api_key: String = #\"9abcdefghijklmno\"#"],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-swift-typed-var",
        &["var api_key: String = \"\"\"\n9abcdefghijklmno\n\"\"\""],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-swift",
        &["func f() { api_key = #\"9abcdefghijklmno\"# }"],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-cpp",
        &["void f() { api_key = R\"(9abcdefghijklmno)\"; }"],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-cpp-auto",
        &["auto api_key = R\"(9abcdefghijklmno)\";"],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-cpp-const-string",
        &["const std::string api_key = R\"(9abcdefghijklmno)\";"],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-dart-declaration",
        &[
            "void f() { final api_key = r'9abcdefghijklmno'; }",
            "void f() { final api_key = '''\n9abcdefghijklmno\n'''; }",
        ],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-dart",
        &["void f() { api_key = r'9abcdefghijklmno'; }"],
    );
    also_invalid(
        &mut cases,
        "hardcoded-credential-dart-typed",
        &["void f() { String api_key = r'9abcdefghijklmno'; }"],
    );
    for lang_id in ["c", "cpp"] {
        also_invalid(
            &mut cases,
            &format!("hardcoded-credential-{lang_id}-const-ptr"),
            &["static const char *api_key = \"9abcdefghijklmno\";"],
        );
        also_invalid(
            &mut cases,
            &format!("hardcoded-credential-{lang_id}-const-array"),
            &["static const char api_key[] = \"9abcdefghijklmno\";"],
        );
        also_invalid(
            &mut cases,
            &format!("hardcoded-credential-{lang_id}-sized-array"),
            &["static char api_key[64] = \"9abcdefghijklmno\";"],
        );
    }
    cases
}

const C_LANG: &[&str] = &["c"];
const CPP_LANG: &[&str] = &["cpp"];

/// A declaration-form case for the modifier and storage-class rules: `{name}`
/// and `{value}` are substituted in `template`, yielding three credential names
/// crossed with three digit-bearing values as invalid snippets, plus short,
/// no-digit and non-credential values and `valid_extra` as valid ones.
fn form_case(
    id: &'static str,
    languages: &'static [&'static str],
    template: &str,
    valid_extra: &[&str],
) -> Case {
    let names = ["api_key", "client_secret", "auth_token"];
    let values = ["9abcdefghijklmno", "abcdefg9hijklmno", "abcdefghijklmno9"];
    let mut invalid = Vec::new();
    for name in names {
        for value in values {
            invalid.push(template.replace("{name}", name).replace("{value}", value));
        }
    }
    let mut valid = vec![
        template
            .replace("{name}", "api_key")
            .replace("{value}", "9abcdefghijklmn"),
        template
            .replace("{name}", "api_key")
            .replace("{value}", "abcdefghijklmnop"),
        template
            .replace("{name}", "settings")
            .replace("{value}", "9abcdefghijklmno"),
    ];
    valid.extend(valid_extra.iter().map(|snippet| (*snippet).to_string()));
    Case::new(id, languages, invalid, valid)
}

/// Add invalid snippets to an already built case.
fn also_invalid(cases: &mut [Case], id: &str, snippets: &[&str]) {
    let case = cases
        .iter_mut()
        .find(|case| case.id == id)
        .unwrap_or_else(|| panic!("no case for {id}"));
    case.invalid.extend(strings(snippets));
}

fn strings(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}
