use super::harness::HarnessId;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Markdown,
    Toml,
}

#[derive(Clone)]
struct FoundKey {
    index: usize,
    raw_value: String,
}

struct Change {
    key_index: usize,
    replacement: Option<String>,
}

fn kind(harness: HarnessId) -> Kind {
    if harness == HarnessId::Codex {
        Kind::Toml
    } else {
        Kind::Markdown
    }
}

fn keys(kind: Kind) -> &'static [&'static str] {
    match kind {
        Kind::Markdown => &["model"],
        Kind::Toml => &["model", "model_reasoning_effort"],
    }
}

fn lines(text: &str) -> Vec<String> {
    text.replace("\r\n", "\n")
        .replace('\r', "\n")
        .split_inclusive('\n')
        .map(str::to_owned)
        .collect()
}

fn without_newline(line: &str) -> &str {
    line.trim_end_matches('\n')
}

fn header_indexes(lines: &[String], kind: Kind) -> Vec<usize> {
    match kind {
        Kind::Markdown => {
            if lines
                .first()
                .is_none_or(|line| without_newline(line) != "---")
            {
                return Vec::new();
            }
            let mut indexes = Vec::new();
            for (index, line) in lines.iter().enumerate().skip(1) {
                if without_newline(line) == "---" {
                    break;
                }
                indexes.push(index);
            }
            indexes
        }
        Kind::Toml => lines
            .iter()
            .enumerate()
            .take_while(|(_, line)| {
                !line.starts_with("developer_instructions") && !line.starts_with('[')
            })
            .map(|(index, _)| index)
            .collect(),
    }
}

fn value_for_key(line: &str, key: &str, kind: Kind) -> Option<String> {
    let line = without_newline(line);
    let remainder = match kind {
        Kind::Markdown => line.strip_prefix(key)?.strip_prefix(':')?,
        Kind::Toml => {
            let after_key = line.strip_prefix(key)?;
            after_key
                .trim_start_matches(char::is_whitespace)
                .strip_prefix('=')?
        }
    };
    Some(
        remainder
            .trim_start_matches(char::is_whitespace)
            .trim_end_matches(char::is_whitespace)
            .to_owned(),
    )
}

fn find_keys(lines: &[String], kind: Kind) -> Vec<Option<FoundKey>> {
    let names = keys(kind);
    let mut found = vec![None; names.len()];
    for index in header_indexes(lines, kind) {
        for (key_index, key) in names.iter().enumerate() {
            if found[key_index].is_none()
                && let Some(raw_value) = value_for_key(&lines[index], key, kind)
            {
                found[key_index] = Some(FoundKey { index, raw_value });
            }
        }
    }
    found
}

fn record_value(line: &str, kind: Kind) -> Option<&str> {
    let line = without_newline(line);
    match kind {
        Kind::Markdown => line
            .strip_prefix("<!-- varde-default: ")?
            .strip_suffix(" -->"),
        Kind::Toml => line.strip_prefix("# varde-default: "),
    }
}

fn unquote(raw: &str) -> String {
    let raw = raw.trim();
    if raw.len() >= 2 {
        let quote = raw.as_bytes()[0];
        if (quote == b'"' || quote == b'\'') && raw.as_bytes()[raw.len() - 1] == quote {
            return raw[1..raw.len() - 1].to_owned();
        }
    }
    raw.to_owned()
}

fn recorded_defaults(lines: &[String], kind: Kind) -> Vec<Option<String>> {
    let names = keys(kind);
    let mut records = vec![None; names.len()];
    for line in lines {
        let Some(record) = record_value(line, kind) else {
            continue;
        };
        for (key_index, key) in names.iter().enumerate() {
            if let Some(value) = value_for_key(record, key, kind) {
                records[key_index] = Some(unquote(&value));
            }
        }
    }
    records
}

fn history(harness: HarnessId, agent: &str, key: &str) -> &'static [&'static str] {
    match (harness, agent, key) {
        (HarnessId::Claude, "varde-reviewer", "model") => &["haiku"],
        (HarnessId::Claude, "varde-explorer", "model") => &["sonnet"],
        (HarnessId::Codex, "varde-explorer", "model") => &["gpt-5.6-luna"],
        (HarnessId::Codex, "varde-builder", "model") => &["gpt-5.6-luna"],
        (HarnessId::Codex, "varde-planner", "model") => &["gpt-5.6-terra"],
        (HarnessId::Codex, "varde-reviewer", "model") => &["gpt-5.6-sol"],
        (HarnessId::Pi, "varde-builder", "model") => &["deepseek/deepseek-v4-flash"],
        (HarnessId::Pi, "varde-explorer", "model") => &["deepseek/deepseek-v4-flash"],
        (HarnessId::Pi, "varde-planner", "model") => &["deepseek/deepseek-v4-flash"],
        (HarnessId::Pi, "varde-reviewer", "model") => &["deepseek/deepseek-v4-flash"],
        _ => &[],
    }
}

fn is_varde_default(
    key_index: usize,
    value: &str,
    shipped: Option<&str>,
    records: &[Option<String>],
    harness: HarnessId,
    agent: &str,
    key: &str,
) -> bool {
    if let Some(record) = &records[key_index] {
        return value == record;
    }
    if shipped.is_some_and(|shipped| value == shipped) {
        return true;
    }
    history(harness, agent, key).contains(&value)
}

fn plan(
    harness: HarnessId,
    agent: &str,
    kind: Kind,
    staged_lines: &[String],
    installed_lines: &[String],
) -> (Vec<Change>, Vec<Option<FoundKey>>) {
    let names = keys(kind);
    let shipped = find_keys(staged_lines, kind);
    let installed = find_keys(installed_lines, kind);
    let records = recorded_defaults(installed_lines, kind);
    let mut changes = Vec::new();

    for (key_index, key) in names.iter().enumerate() {
        if let Some(shipped_key) = &shipped[key_index] {
            if let Some(installed_key) = &installed[key_index] {
                if !is_varde_default(
                    key_index,
                    &unquote(&installed_key.raw_value),
                    Some(&unquote(&shipped_key.raw_value)),
                    &records,
                    harness,
                    agent,
                    key,
                ) {
                    changes.push(Change {
                        key_index,
                        replacement: Some(installed_lines[installed_key.index].clone()),
                    });
                }
            } else if records[key_index].is_some() {
                changes.push(Change {
                    key_index,
                    replacement: None,
                });
            }
        } else if kind == Kind::Markdown
            && let Some(installed_key) = &installed[key_index]
        {
            let once_shipped =
                records[key_index].is_some() || !history(harness, agent, key).is_empty();
            if once_shipped
                && !is_varde_default(
                    key_index,
                    &unquote(&installed_key.raw_value),
                    None,
                    &records,
                    harness,
                    agent,
                    key,
                )
            {
                changes.push(Change {
                    key_index,
                    replacement: Some(installed_lines[installed_key.index].clone()),
                });
            }
        }
    }

    (changes, shipped)
}

fn insert_at(lines: &[String]) -> usize {
    let header = header_indexes(lines, Kind::Markdown);
    for index in &header {
        if lines[*index].starts_with("description:") {
            return index + 1;
        }
    }
    header.last().map_or(lines.len(), |index| index + 1)
}

fn rewrite(
    kind: Kind,
    staged_lines: &[String],
    changes: &[Change],
    shipped: &[Option<FoundKey>],
) -> String {
    let mut output = staged_lines.to_vec();
    let mut deleted = Vec::new();
    let mut insertions = Vec::new();

    for change in changes {
        if let Some(shipped_key) = &shipped[change.key_index] {
            match &change.replacement {
                Some(replacement) => output[shipped_key.index] = replacement.clone(),
                None => deleted.push(shipped_key.index),
            }
        } else if let Some(replacement) = &change.replacement {
            insertions.push(replacement.clone());
        }
    }
    if !deleted.is_empty() {
        output = output
            .into_iter()
            .enumerate()
            .filter_map(|(index, line)| (!deleted.contains(&index)).then_some(line))
            .collect();
    }
    for insertion in insertions {
        let insertion = if insertion.ends_with('\n') {
            insertion
        } else {
            format!("{insertion}\n")
        };
        output.insert(insert_at(&output), insertion);
    }
    if let Some(last_line) = output.last_mut()
        && !last_line.ends_with('\n')
    {
        last_line.push('\n');
    }

    for (key_index, _) in keys(kind).iter().enumerate() {
        if let Some(shipped_key) = &shipped[key_index] {
            let original = without_newline(&staged_lines[shipped_key.index]);
            match kind {
                Kind::Markdown => {
                    output.push(format!("<!-- varde-default: {original} -->\n"));
                }
                Kind::Toml => output.push(format!("# varde-default: {original}\n")),
            }
        }
    }
    output.concat()
}

fn preserved_keys(changes: &[Change], kind: Kind) -> Vec<String> {
    changes
        .iter()
        .map(|change| keys(kind)[change.key_index].to_owned())
        .collect()
}

/// Preserve user-selected model settings while refreshing the staged variant.
pub fn preserve_models(
    harness: HarnessId,
    agent: &str,
    staged: &str,
    installed: Option<&str>,
) -> (String, Vec<String>) {
    let format = kind(harness);
    let staged_lines = lines(staged);
    let (changes, shipped) = match installed {
        Some(installed) => plan(harness, agent, format, &staged_lines, &lines(installed)),
        None => (Vec::new(), find_keys(&staged_lines, format)),
    };
    let preserved = preserved_keys(&changes, format);
    (
        rewrite(format, &staged_lines, &changes, &shipped),
        preserved,
    )
}

/// Return the keys that would be preserved without rewriting the staged text.
pub fn dry_run(
    harness: HarnessId,
    agent: &str,
    staged: &str,
    installed: Option<&str>,
) -> Vec<String> {
    let format = kind(harness);
    let Some(installed) = installed else {
        return Vec::new();
    };
    let (changes, _) = plan(harness, agent, format, &lines(staged), &lines(installed));
    preserved_keys(&changes, format)
}
