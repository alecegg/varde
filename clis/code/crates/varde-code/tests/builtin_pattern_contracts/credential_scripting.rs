use super::Case;

/// Fixture contracts for scripting hardcoded-credential rules.
///
/// Ruby, PHP, Lua and Bash each keep their binding rule; PHP adds `const` and
/// the two `define(...)` quote forms. Every rule shares the same KEY and VAL
/// constraints as `hardcoded-credential-literal`; the shared KEY accepts the
/// Ruby `@`/`@@` prefix, so instance and class variables are invalid cases.
///
/// Raw and multiline literals are invalid cases: Ruby `%q(...)`/`%Q{...}`, PHP
/// heredoc/nowdoc, Lua long brackets (`[[...]]`, `[=[...]=]`). The Bash
/// `export`, `readonly`, `declare` and `local` declaration forms wrap the same
/// `variable_assignment` node as a plain assignment and are invalid cases too.
/// Interpolated content (`#{...}`, `${...}`, `$(...)`, `$var`) stays valid: the
/// shared VAL rejects those characters.
///
/// Deliberate non-cases, matching the pack header: Ruby heredocs (the capture
/// is only the `<<~EOT` beginning, so no content evidence exists) and Lua table
/// fields (ast-grep cannot parse a bare `field` pattern). `exclude_test_paths`
/// is path-based, so it does not change these fixtures.
pub fn cases() -> Vec<Case> {
    let ruby = Case::new(
        "hardcoded-credential-ruby",
        &["ruby"],
        vec![
            "api_key = \"9abcdefghijklmno\"".to_string(),
            "password = \"9abcdefghijklmno\"".to_string(),
            "API_KEY = \"abcdefg9hijklmno\"".to_string(),
            "session_token = 'abcdefg9hijklmno'".to_string(),
            "@api_key = \"9abcdefghijklmno\"".to_string(),
            "@@client_secret = \"abcdefg9hijklmno\"".to_string(),
            "api_key = %q(9abcdefghijklmno)".to_string(),
            "api_key = %Q{abcdefg9hijklmno}".to_string(),
        ],
        vec![
            "api_key = \"9abcdefghijklmn\"".to_string(),
            "api_key = \"abcdefghijklmnop\"".to_string(),
            "not_the_key = \"9abcdefghijklmno\"".to_string(),
            "api_key = ENV[\"API_KEY\"]".to_string(),
            "api_key = ENV.fetch(\"API_KEY\")".to_string(),
            "config.api_key = \"9abcdefghijklmno\"".to_string(),
            "config = { api_key: \"9abcdefghijklmno\" }".to_string(),
            "api_key = \"abc#{secret}9abcdefghijklmno\"".to_string(),
            "api_key = %Q(abc#{secret}9abcdefghijklmno)".to_string(),
            // A heredoc capture is only the `<<~EOT` beginning.
            "api_key = <<~EOT\n9abcdefghijklmno\nEOT".to_string(),
        ],
    );
    let php = Case::new(
        "hardcoded-credential-php",
        &["php"],
        vec![
            "<?php $api_key = \"9abcdefghijklmno\";".to_string(),
            "<?php $password = \"9abcdefghijklmno\";".to_string(),
            "<?php $session_token = 'abcdefg9hijklmno';".to_string(),
            "<?php $api_key = <<<'EOT'\n9abcdefghijklmno\nEOT;".to_string(),
            "<?php $api_key = <<<EOT\nabcdefg9hijklmno\nEOT;".to_string(),
        ],
        vec![
            "<?php $api_key = \"9abcdefghijklmn\";".to_string(),
            "<?php $api_key = \"abcdefghijklmnop\";".to_string(),
            "<?php $not_the_key = \"9abcdefghijklmno\";".to_string(),
            "<?php $api_key = getenv(\"API_KEY\");".to_string(),
            "<?php $config->api_key = \"9abcdefghijklmno\";".to_string(),
            "<?php $config['api_key'] = \"9abcdefghijklmno\";".to_string(),
            "<?php $api_key = \"abc${secret}9abcdefghijklmno\";".to_string(),
            "<?php $api_key = <<<EOT\n$secret\nEOT;".to_string(),
        ],
    );
    let php_const = Case::new(
        "hardcoded-credential-php-const",
        &["php"],
        vec![
            "<?php const API_KEY = \"9abcdefghijklmno\";".to_string(),
            "<?php const SESSION_TOKEN = 'abcdefg9hijklmno';".to_string(),
            "<?php class C { const PASSWORD = \"abcdefghijklmno9\"; }".to_string(),
        ],
        vec![
            "<?php const API_KEY = \"9abcdefghijklmn\";".to_string(),
            "<?php const API_KEY = \"abcdefghijklmnop\";".to_string(),
            "<?php const NOT_THE_KEY = \"9abcdefghijklmno\";".to_string(),
            "<?php const API_KEY = getenv(\"API_KEY\");".to_string(),
            // A variable assignment belongs to the assignment rule.
            "<?php $api_key = \"9abcdefghijklmno\";".to_string(),
            // A `define(...)` call belongs to the define rules.
            "<?php define('API_KEY', \"9abcdefghijklmno\");".to_string(),
        ],
    );
    let php_define = Case::new(
        "hardcoded-credential-php-define",
        &["php"],
        vec![
            "<?php define('API_KEY', \"9abcdefghijklmno\");".to_string(),
            "<?php define('SESSION_TOKEN', 'abcdefg9hijklmno');".to_string(),
        ],
        vec![
            "<?php define('API_KEY', \"9abcdefghijklmn\");".to_string(),
            "<?php define('API_KEY', \"abcdefghijklmnop\");".to_string(),
            "<?php define('NOT_THE_KEY', \"9abcdefghijklmno\");".to_string(),
            "<?php define('API_KEY', getenv('API_KEY'));".to_string(),
            // Double-quoted define name belongs to the double-quote rule.
            "<?php define(\"API_KEY\", \"9abcdefghijklmno\");".to_string(),
        ],
    );
    let php_define_double = Case::new(
        "hardcoded-credential-php-define-double",
        &["php"],
        vec![
            "<?php define(\"API_KEY\", \"9abcdefghijklmno\");".to_string(),
            "<?php define(\"CLIENT_SECRET\", 'abcdefg9hijklmno');".to_string(),
        ],
        vec![
            "<?php define(\"API_KEY\", \"9abcdefghijklmn\");".to_string(),
            "<?php define(\"NOT_THE_KEY\", \"9abcdefghijklmno\");".to_string(),
            "<?php define(\"API_KEY\", getenv('API_KEY'));".to_string(),
            "<?php define(\"API_KEY\", \"abc${secret}9abcdefghijklmno\");".to_string(),
            // Single-quoted define name belongs to the single-quote rule.
            "<?php define('API_KEY', \"9abcdefghijklmno\");".to_string(),
        ],
    );
    let lua = Case::new(
        "hardcoded-credential-lua",
        &["lua"],
        vec![
            "local api_key = \"9abcdefghijklmno\"".to_string(),
            "local session_token = 'abcdefg9hijklmno'".to_string(),
            "api_key = \"9abcdefghijklmno\"".to_string(),
            "token = \"abcdefg9hijklmno\"".to_string(),
            "local api_key = [[9abcdefghijklmno]]".to_string(),
            "local api_key = [=[abcdefg9hijklmno]=]".to_string(),
        ],
        vec![
            "local api_key = \"9abcdefghijklmn\"".to_string(),
            "local api_key = \"abcdefghijklmnop\"".to_string(),
            "local not_the_key = \"9abcdefghijklmno\"".to_string(),
            "local api_key = os.getenv(\"API_KEY\")".to_string(),
            // Lua table fields are not matchable as a pattern root.
            "local config = { api_key = \"9abcdefghijklmno\" }".to_string(),
            "config.api_key = \"9abcdefghijklmno\"".to_string(),
            "config[\"api_key\"] = \"9abcdefghijklmno\"".to_string(),
        ],
    );
    let bash = Case::new(
        "hardcoded-credential-bash",
        &["bash"],
        vec![
            "API_KEY=\"9abcdefghijklmno\"".to_string(),
            "password='9abcdefghijklmno'".to_string(),
            "SESSION_TOKEN=\"abcdefg9hijklmno\"".to_string(),
            "export API_KEY=\"9abcdefghijklmno\"".to_string(),
            "readonly API_KEY=\"9abcdefghijklmno\"".to_string(),
            "declare API_KEY=\"9abcdefghijklmno\"".to_string(),
            "local API_KEY=\"9abcdefghijklmno\"".to_string(),
        ],
        vec![
            "API_KEY=\"9abcdefghijklmn\"".to_string(),
            "API_KEY=\"abcdefghijklmnop\"".to_string(),
            "NOT_THE_KEY=\"9abcdefghijklmno\"".to_string(),
            "API_KEY=\"${API_KEY_ENV}\"".to_string(),
            "API_KEY=\"$(cat /run/secrets/key)\"".to_string(),
            "API_KEY=$(vault read key)".to_string(),
            "export API_KEY=\"$(vault read key)\"".to_string(),
        ],
    );
    vec![
        ruby,
        php,
        php_const,
        php_define,
        php_define_double,
        lua,
        bash,
    ]
}
