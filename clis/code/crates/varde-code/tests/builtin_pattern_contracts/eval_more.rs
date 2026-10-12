use super::Case;

pub fn cases() -> Vec<Case> {
    vec![
        Case::new(
            "eval-usage-ruby",
            &["ruby"],
            vec!["eval(source)".into()],
            vec!["safe_eval(source)".into(), "object.eval(source)".into()],
        ),
        Case::new(
            "eval-usage-php",
            &["php"],
            vec!["<?php eval($source);".into()],
            vec!["<?php safe_eval($source);".into(), "<?php $object->eval($source);".into()],
        ),
        Case::new(
            "eval-usage-lua",
            &["lua"],
            vec!["load(source)".into()],
            vec!["safe_load(source)".into(), "object.load(source)".into()],
        ),
        Case::new(
            "eval-usage-bash",
            &["bash"],
            vec!["eval \"$source\"".into()],
            vec!["safe_eval \"$source\"".into()],
        ),
        Case::new(
            "eval-usage-elixir",
            &["elixir"],
            vec!["Code.eval_string(source)".into()],
            vec!["safe_eval_string(source)".into(), "Other.eval_string(source)".into()],
        ),
    ]
}
