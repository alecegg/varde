//! `varde doc frontmatter`: every case of `test-frontmatter-validator.py`,
//! plus the YAML 1.1 versus 1.2 divergences documented in `src/frontmatter.rs`.

use std::fs;
use std::path::{Path, PathBuf};
use varde_doc::frontmatter::{self, InputError, SkillResult};

const DESCRIPTION: &str = "description: \"Example skill\"\n";

fn write_skill(root: &Path, dir: &str, content: &str) -> PathBuf {
    let skill = root.join(dir);
    fs::create_dir_all(&skill).unwrap();
    fs::write(skill.join("SKILL.md"), content).unwrap();
    skill
}

/// Validate a skill named `sample`, as the Python helper does.
fn validate_with(extra: &str, description: &str, valid: bool) -> SkillResult {
    let tmp = tempfile::tempdir().unwrap();
    let content = format!("---\nname: sample\n{description}{extra}---\n# Sample\n");
    let skill = write_skill(tmp.path(), "sample", &content);
    let results = frontmatter::check(&[skill]).unwrap();
    assert_eq!(results.len(), 1);
    let result = results.into_iter().next().unwrap();
    assert_eq!(result.ok(), valid, "{extra:?}: {result:?}");
    if !valid {
        assert!(!result.errors.is_empty());
    }
    result
}

fn validate(extra: &str, valid: bool) -> SkillResult {
    validate_with(extra, DESCRIPTION, valid)
}

#[test]
fn duplicate_keys() {
    for extra in [
        "name: sample\n",
        "description: Different description\n",
        "metadata:\n  owner: one\n  owner: two\n",
        "defaults: &defaults\n  owner: one\n  owner: two\nmetadata:\n  <<: *defaults\n",
        "metadata:\n  <<: {owner: one}\n  <<: {owner: two}\n",
    ] {
        let result = validate(extra, false);
        assert!(
            result.errors[0].contains("duplicate key"),
            "{extra:?}: {result:?}"
        );
    }
}

#[test]
fn unique_and_mixed_unknown_keys() {
    validate("metadata:\n  owner: one\n", true);
    let result = validate("1: foo\nextra: bar\n", true);
    assert_eq!(
        result.warnings,
        [
            "unrecognized frontmatter field `1` (client-specific fields are fine)",
            "unrecognized frontmatter field `extra` (client-specific fields are fine)",
        ]
    );
}

#[test]
fn description_physical_line() {
    validate_with("", "description: \"A single line\"\n", true);
    for description in [
        "description: Plain text\n",
        "description: 'Single quoted'\n",
        "description: >\n  Folded text\n",
        "description: |\n  Literal text\n",
        "description: \"First line\n  second line\"\n",
        "description: &value \"Anchored\"\n",
    ] {
        let result = validate_with("", description, false);
        assert!(
            result
                .errors
                .contains(&"`description` must be one double-quoted physical line".to_string()),
            "{description:?}: {result:?}"
        );
    }
}

#[test]
fn merge_overrides_and_aliases() {
    for extra in [
        "metadata:\n  <<: {owner: inherited}\n  owner: explicit\n",
        "metadata:\n  <<: [{owner: first}, {owner: second}]\n",
        "defaults: &defaults\n  <<: {owner: inherited}\n  owner: explicit\nmetadata:\n  <<: *defaults\n",
        "defaults: &defaults\n  <<: {owner: inherited}\n  owner: explicit\nmetadata: *defaults\n",
        // An explicit string overrides an inherited non-string.
        "metadata:\n  <<: {owner: 5}\n  owner: explicit\n",
    ] {
        validate(extra, true);
    }
    // A non-string that survives the merge is still rejected.
    validate("metadata:\n  <<: {owner: 5}\n", false);
    validate("metadata:\n  <<: [{owner: 5}, {owner: first}]\n", false);
}

#[test]
fn unhashable_and_unsafe_keys() {
    validate("? [one, two]\n: value\n", false);
    validate("extra: !!python/object:builtins.object {}\n", false);
}

#[test]
fn real_skill() {
    let skill =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../../skills/varde-agent-doc-authoring");
    let results = frontmatter::check(&[skill]).unwrap();
    assert_eq!(results.len(), 1);
    assert!(results[0].ok(), "{:?}", results[0]);
}

// YAML 1.1 (PyYAML) versus 1.2 (serde_yaml): intended divergences.

#[test]
fn yaml_1_1_bool_like_metadata_values_are_strings() {
    for value in ["yes", "no", "on", "off", "y", "Yes", "1_000", "1:30"] {
        validate(&format!("metadata:\n  owner: {value}\n"), true);
    }
    // Real YAML 1.2 non-strings still fail.
    for value in ["true", "false", "null", "5", "0o17", "1.5", "[a]", "{a: b}"] {
        validate(&format!("metadata:\n  owner: {value}\n"), false);
    }
}

#[test]
fn explicit_tags_are_rejected() {
    let result = validate("metadata:\n  owner: !!str one\n", false);
    assert!(result.errors[0].starts_with("frontmatter is not valid YAML: "));
}

#[test]
fn explicit_tags_in_multiline_flow_collections_are_rejected() {
    validate("extra: [a,\n  b, !!python/object:x c]\n", false);
}

#[test]
fn bang_bang_in_quotes_comments_and_plain_text_is_not_a_tag() {
    validate(
        "note: \"wow !!x\"  # !!y\nother: 'it''s !!z'\nplain: hi!!\n",
        true,
    );
    validate("# !!str\nlist: [a, !!str b]\n", false);
}

#[test]
fn merge_keys_flow_through_metadata_and_unknown_keys() {
    let result = validate("base: &b\n  owner: one\nmetadata:\n  <<: *b\n", true);
    assert_eq!(result.warnings.len(), 1);
    assert!(result.warnings[0].contains("`base`"));
}

#[test]
fn duplicate_keys_inside_nested_and_merged_mappings_are_rejected() {
    validate("extra:\n  a: 1\n  a: 2\n", false);
    validate("base: &b {a: 1, a: 2}\nmetadata:\n  <<: *b\n", false);
    validate("metadata:\n  <<: [{a: x, a: y}]\n", false);
}

#[test]
fn merged_description_is_not_subject_to_the_line_check() {
    let tmp = tempfile::tempdir().unwrap();
    let content = "---\nname: sample\n<<: {description: inherited}\n---\n";
    let skill = write_skill(tmp.path(), "sample", content);
    let results = frontmatter::check(&[skill]).unwrap();
    assert!(results[0].ok(), "{:?}", results[0]);
}

// Field rules.

fn check_text(dir: &str, content: &str) -> SkillResult {
    let tmp = tempfile::tempdir().unwrap();
    let skill = write_skill(tmp.path(), dir, content);
    frontmatter::check(&[skill]).unwrap().remove(0)
}

fn errors(dir: &str, content: &str) -> Vec<String> {
    check_text(dir, content).errors
}

#[test]
fn missing_or_malformed_frontmatter() {
    assert_eq!(
        errors("s", "# Title\n"),
        ["no `---`-delimited YAML frontmatter block found at the top of the file"]
    );
    assert_eq!(
        errors("s", "---\n---\n"),
        ["no `---`-delimited YAML frontmatter block found at the top of the file"]
    );
    assert_eq!(
        errors("s", "---\n- a\n- b\n---\n"),
        ["frontmatter must be a YAML mapping (key: value pairs)"]
    );
    assert_eq!(
        errors("s", "---\n\n---\n"),
        ["frontmatter must be a YAML mapping (key: value pairs)"]
    );
    let bad = errors("s", "---\nname: a: b\n---\n");
    assert!(
        bad[0].starts_with("frontmatter is not valid YAML: "),
        "{bad:?}"
    );
}

#[test]
fn name_rules() {
    let long = "a".repeat(65);
    let content = format!("---\nname: {long}\ndescription: \"d\"\n---\n");
    let found = errors(&long, &content);
    assert_eq!(found, ["`name` is 65 chars, max is 64"]);
    assert_eq!(
        errors(
            "Bad--Name",
            "---\nname: Bad--Name\ndescription: \"d\"\n---\n"
        ),
        [
            "`name` 'Bad--Name' must be lowercase alphanumeric + hyphens only, no leading/trailing hyphen, no consecutive hyphens"
        ]
    );
    assert_eq!(
        errors("other", "---\nname: sample\ndescription: \"d\"\n---\n"),
        ["`name` 'sample' must match parent directory name 'other'"]
    );
    assert_eq!(
        errors("s", "---\ndescription: \"d\"\n---\n"),
        ["missing required field `name`"]
    );
    assert_eq!(
        errors("s", "---\nname: 0\ndescription: \"d\"\n---\n"),
        ["missing required field `name`"]
    );
    assert_eq!(
        errors("s", "---\nname: 12\ndescription: \"d\"\n---\n"),
        ["`name` must be a string, got int"]
    );
    assert_eq!(
        errors("s", "---\nname: 1.5\ndescription: \"d\"\n---\n"),
        ["`name` must be a string, got float"]
    );
    assert_eq!(
        errors("s", "---\nname: [a]\ndescription: \"d\"\n---\n"),
        ["`name` must be a string, got list"]
    );
    assert_eq!(
        errors("it's", "---\nname: \"it's\"\ndescription: \"d\"\n---\n"),
        [
            "`name` \"it's\" must be lowercase alphanumeric + hyphens only, no leading/trailing hyphen, no consecutive hyphens"
        ]
    );
}

#[test]
fn description_rules() {
    assert_eq!(
        errors("s", "---\nname: s\n---\n"),
        ["missing required field `description`"]
    );
    assert_eq!(
        errors("s", "---\nname: s\ndescription: \"  \"\n---\n"),
        ["missing required field `description`"]
    );
    assert_eq!(
        errors("s", "---\nname: s\ndescription: 5\n---\n"),
        [
            "`description` must be a string, got int",
            "`description` must be one double-quoted physical line"
        ]
    );
    let long = "x".repeat(1025);
    assert_eq!(
        errors(
            "s",
            &format!("---\nname: s\ndescription: \"{long}\"\n---\n")
        ),
        ["`description` is 1025 chars, max is 1024"]
    );
    // Escaped quotes stay on one line.
    assert!(errors("s", "---\nname: s\ndescription: \"say \\\"hi\\\"\"\n---\n").is_empty());
}

#[test]
fn optional_field_rules() {
    let base = "---\nname: s\ndescription: \"d\"\n";
    assert_eq!(
        errors("s", &format!("{base}compatibility: 5\n---\n")),
        ["`compatibility` must be a string, got int"]
    );
    let long = "c".repeat(501);
    assert_eq!(
        errors("s", &format!("{base}compatibility: {long}\n---\n")),
        ["`compatibility` is 501 chars, max is 500"]
    );
    assert!(errors("s", &format!("{base}compatibility:\n---\n")).is_empty());
    assert_eq!(
        errors("s", &format!("{base}metadata: [a]\n---\n")),
        ["`metadata` must be a map of string keys to string values"]
    );
    assert_eq!(
        errors("s", &format!("{base}metadata:\n  1: a\n---\n")),
        ["`metadata` must be a map of string keys to string values"]
    );
    assert_eq!(
        errors("s", &format!("{base}allowed-tools: [a]\n---\n")),
        ["`allowed-tools` must be a string, got list"]
    );
    assert!(
        errors(
            "s",
            &format!("{base}allowed-tools: Bash\nlicense: MIT\n---\n")
        )
        .is_empty()
    );
}

#[test]
fn unknown_keys_warn_in_python_string_order() {
    let result = check_text(
        "s",
        "---\nname: s\ndescription: \"d\"\nzeta: 1\ntrue: 2\n~: 3\nalpha: 4\n---\n",
    );
    let keys: Vec<_> = result
        .warnings
        .iter()
        .map(|w| w.split('`').nth(1).unwrap().to_string())
        .collect();
    assert_eq!(keys, ["None", "True", "alpha", "zeta"]);
}

#[test]
fn body_line_budget_warns_over_500_lines() {
    let head = "---\nname: s\ndescription: \"d\"\n---\n";
    // `n` newlines after the frontmatter make a body of n + 1 lines.
    let at_budget = format!("{head}{}", "x\n".repeat(499));
    assert!(check_text("s", &at_budget).warnings.is_empty());
    let over = format!("{head}{}", "x\n".repeat(500));
    assert_eq!(
        check_text("s", &over).warnings,
        [
            "SKILL.md body is ~501 lines, over the 500-line soft budget \u{2014} consider moving detail into references/, assets/, or scripts/"
        ]
    );
}

#[test]
fn crlf_files_validate_like_lf_files() {
    let result = check_text(
        "s",
        "---\r\nname: s\r\ndescription: \"d\"\r\n---\r\n# Body\r\n",
    );
    assert!(result.ok(), "{result:?}");
}

#[test]
fn text_after_closing_delimiter_is_accepted() {
    let result = check_text("s", "---\nname: s\ndescription: \"d\"\n---trailing\n");
    assert!(result.ok(), "{result:?}");
}

// Skill `requires`/`recommends` relations.

/// Build a root of skills and validate every one of them.
fn relations_root(skills: &[(&str, &str)]) -> Vec<SkillResult> {
    let tmp = tempfile::tempdir().unwrap();
    for (name, relations) in skills {
        let content = format!("---\nname: {name}\ndescription: \"d\"\n{relations}---\n");
        write_skill(tmp.path(), name, &content);
    }
    frontmatter::check(&[tmp.path().to_path_buf()]).unwrap()
}

fn errors_for(results: &[SkillResult], name: &str) -> Vec<String> {
    results
        .iter()
        .find(|result| result.path.contains(&format!("/{name}/")))
        .unwrap_or_else(|| panic!("no result for `{name}` in {results:?}"))
        .errors
        .clone()
}

#[test]
fn relation_keys_are_known_fields() {
    let results = relations_root(&[("s", "requires: []\nrecommends: []\n")]);
    assert!(results[0].errors.is_empty(), "{:?}", results[0]);
    assert!(results[0].warnings.is_empty(), "{:?}", results[0]);
}

#[test]
fn a_known_require_and_recommend_pass() {
    let results = relations_root(&[
        ("s", "requires: [dep]\nrecommends: [extra]\n"),
        ("dep", ""),
        ("extra", ""),
    ]);
    assert!(results.iter().all(SkillResult::ok), "{results:?}");
}

#[test]
fn unknown_require_and_recommend_names_are_rejected() {
    assert_eq!(
        errors_for(&relations_root(&[("s", "requires: [missing]\n")]), "s"),
        ["`requires` names unknown skill `missing`"]
    );
    assert_eq!(
        errors_for(&relations_root(&[("s", "recommends: [missing]\n")]), "s"),
        ["`recommends` names unknown skill `missing`"]
    );
}

#[test]
fn self_reference_and_cycles_are_rejected() {
    let errors = errors_for(&relations_root(&[("s", "requires: [s]\n")]), "s");
    assert!(
        errors
            .iter()
            .any(|error| error.contains("cycle") && error.contains('s')),
        "{errors:?}"
    );
    let results = relations_root(&[("s", "requires: [a]\n"), ("a", "requires: [s]\n")]);
    let errors = errors_for(&results, "s");
    assert!(
        errors
            .iter()
            .any(|error| error.contains("cycle") && error.contains('a')),
        "{errors:?}"
    );
}

#[test]
fn the_implicit_skill_must_not_be_listed() {
    let results = relations_root(&[("s", "requires: [varde-manage]\n"), ("varde-manage", "")]);
    let errors = errors_for(&results, "s");
    assert!(
        errors
            .iter()
            .any(|error| error.contains("must not list `varde-manage`")),
        "{errors:?}"
    );
}

#[test]
fn recommends_does_not_resolve_requires() {
    let results = relations_root(&[
        ("s", "recommends: [dep]\n"),
        ("dep", "requires: [missing]\n"),
    ]);
    assert!(errors_for(&results, "s").is_empty(), "{results:?}");
    assert!(!errors_for(&results, "dep").is_empty());
}

#[test]
fn malformed_relation_values_are_rejected() {
    let errors = errors_for(&relations_root(&[("s", "requires: {a: b}\n")]), "s");
    assert!(
        errors
            .iter()
            .any(|error| error.contains("is not a flow list of skill names")),
        "{errors:?}"
    );
}

// Path handling and output.

#[test]
fn finds_skill_dirs_files_and_one_level_of_children() {
    let tmp = tempfile::tempdir().unwrap();
    let ok = "---\nname: NAME\ndescription: \"d\"\n";
    let a = write_skill(tmp.path(), "a", &format!("{ok}---\n").replace("NAME", "a"));
    write_skill(tmp.path(), "b", &format!("{ok}---\n").replace("NAME", "b"));
    fs::create_dir_all(tmp.path().join("empty")).unwrap();
    fs::create_dir_all(tmp.path().join("b/nested/c")).unwrap();

    let root = frontmatter::check(&[tmp.path().to_path_buf()]).unwrap();
    let paths: Vec<_> = root.iter().map(|r| r.path.clone()).collect();
    let prefix = tmp.path().display();
    assert_eq!(
        paths,
        [
            format!("{prefix}/a/SKILL.md"),
            format!("{prefix}/b/SKILL.md")
        ]
    );
    assert!(root.iter().all(SkillResult::ok));

    let file = frontmatter::check(&[a.join("SKILL.md")]).unwrap();
    assert_eq!(file[0].path, format!("{prefix}/a/SKILL.md"));
    let trailing = frontmatter::check(&[PathBuf::from(format!("{prefix}/a/"))]).unwrap();
    assert_eq!(trailing[0].path, format!("{prefix}/a/SKILL.md"));
}

#[test]
fn input_errors() {
    let tmp = tempfile::tempdir().unwrap();
    let missing = tmp.path().join("nope");
    let Err(InputError(message)) = frontmatter::check(std::slice::from_ref(&missing)) else {
        panic!("missing path should fail");
    };
    assert_eq!(
        message,
        format!(
            "varde doc frontmatter: path not found: {}",
            missing.display()
        )
    );
    let empty = tmp.path().join("empty");
    fs::create_dir_all(&empty).unwrap();
    let Err(InputError(message)) = frontmatter::check(std::slice::from_ref(&empty)) else {
        panic!("empty dir should fail");
    };
    assert_eq!(
        message,
        format!(
            "varde doc frontmatter: no SKILL.md found at or under {}",
            empty.display()
        )
    );
    fs::write(tmp.path().join("README.md"), "x").unwrap();
    assert!(frontmatter::check(&[tmp.path().join("README.md")]).is_err());
}

#[test]
fn text_output_matches_the_python_script() {
    let tmp = tempfile::tempdir().unwrap();
    write_skill(
        tmp.path(),
        "good",
        "---\nname: good\ndescription: \"d\"\nextra: 1\n---\n",
    );
    write_skill(tmp.path(), "bad", "---\nname: wrong\ndescription: d\n---\n");
    let results = frontmatter::check(&[tmp.path().to_path_buf()]).unwrap();
    let text =
        frontmatter::render_text(&results).replace(&format!("{}/", tmp.path().display()), "");
    assert_eq!(
        text,
        "FAIL  bad/SKILL.md\n\
         \x20     error:   `name` 'wrong' must match parent directory name 'bad'\n\
         \x20     error:   `description` must be one double-quoted physical line\n\
         OK    good/SKILL.md\n\
         \x20     warning: unrecognized frontmatter field `extra` (client-specific fields are fine)\n"
    );
}

#[test]
fn tags_are_found_only_where_yaml_allows_them() {
    // An apostrophe in a plain scalar does not open a quote.
    validate(
        "compatibility: rock 'n roll\nextra: !!python/object:builtins.object {}\n",
        false,
    );
    // An unbalanced quote inside a block scalar does not hide a later tag.
    validate("notes: |\n  say \"foo\n  bar\nextra: !!str x\n", false);
    // A tag-like word inside a block scalar body is text.
    validate("notes: |\n  keep !!str as is\n", true);
    validate("compatibility: wow !! great\n", true);
    validate("extra: !!str value\n", false);
    validate("extra: &a !!str value\n", false);
    validate("list:\n  - !!str x\n", false);
}

#[test]
fn duplicate_key_wording_is_normalized() {
    let result = validate("a: {x: 1, x: 2}\n", false);
    assert!(result.errors[0].contains("duplicate key"), "{result:?}");
    let result = validate("~: 1\n~: 2\n", false);
    assert!(result.errors[0].contains("duplicate key"), "{result:?}");
    assert!(!result.errors[0].contains("duplicate entry"), "{result:?}");
}

#[test]
fn quoted_merge_key_is_an_ordinary_key() {
    let result = validate("\"<<\": {owner: x}\n", true);
    assert!(
        result.warnings.iter().any(|w| w.contains("<<")),
        "{result:?}"
    );
    validate("'<<': 5\n", true);
}

#[test]
fn no_skill_found_message_names_the_given_path() {
    let Err(InputError(message)) = frontmatter::check(&[PathBuf::from(".")]) else {
        panic!("the crate directory has no SKILL.md");
    };
    assert_eq!(
        message,
        "varde doc frontmatter: no SKILL.md found at or under ."
    );
}
