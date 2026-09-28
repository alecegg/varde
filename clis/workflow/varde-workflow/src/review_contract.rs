//! Canonical contract representation and versioned SHA-1 fingerprints.

use crate::review_gates;
use anyhow::{Context, Result, anyhow};
use serde_json::{Map, Value, json};
use serde_yaml::Value as YamlValue;
use sha1::{Digest, Sha1};
use std::collections::BTreeMap;
use std::path::Path;

const HASH_PREFIX: &str = "sha1-v1:";

pub(crate) fn contract_fingerprint(bytes: &[u8]) -> Result<String> {
    let (frontmatter, body) = varde_workflow_core::frontmatter::parse(bytes).map_err(|error| {
        review_gates::invalid(format!(
            "plan contract must have valid YAML frontmatter: {error}"
        ))
    })?;
    let frontmatter = normalized_frontmatter(&frontmatter).map_err(|error| {
        review_gates::invalid(format!("plan frontmatter cannot be normalized: {error}"))
    })?;
    let body = normalize_markdown_body(&body);
    fingerprint_json(
        "varde-review-contract-v1",
        &json!({ "frontmatter": frontmatter, "body": body }),
    )
}

pub(crate) fn current_contract_fingerprint(
    plan_path: Option<&Path>,
    bounded_contract: Option<&Value>,
) -> Result<String> {
    if let Some(path) = plan_path {
        return contract_fingerprint(
            &std::fs::read(path)
                .with_context(|| format!("failed to read plan {}", path.display()))?,
        );
    }
    let contract = bounded_contract
        .ok_or_else(|| review_gates::invalid("bounded review subject has no contract"))?;
    fingerprint_json("varde-review-bounded-contract-v1", contract)
}

pub(crate) fn parse_bounded_contract(bytes: &[u8]) -> Result<Value> {
    let value: Value = serde_json::from_slice(bytes).map_err(|error| {
        review_gates::invalid(format!(
            "bounded review contract must be valid JSON: {error}"
        ))
    })?;
    let Some(object) = value.as_object() else {
        return Err(review_gates::invalid(
            "bounded review contract must be a JSON object",
        ));
    };
    for key in ["outcome", "scope", "assumptions", "design", "verification"] {
        if !object.contains_key(key) {
            return Err(review_gates::invalid(format!(
                "bounded review contract is missing `{key}`"
            )));
        }
    }
    if !object.contains_key("open_questions") && !object.contains_key("open_choices") {
        return Err(review_gates::invalid(
            "bounded review contract requires `open_questions` or `open_choices`",
        ));
    }
    canonical_json(&value)
}

pub(crate) fn fingerprint_json(tag: &str, value: &Value) -> Result<String> {
    let normalized = canonical_json(value)?;
    Ok(hash_bytes(
        tag.as_bytes(),
        &serde_json::to_vec(&normalized)?,
    ))
}

pub(crate) fn fingerprint_parts<'a>(
    tag: &str,
    parts: impl IntoIterator<Item = &'a [u8]>,
) -> String {
    let mut hash = Sha1::new();
    hash.update(tag.as_bytes());
    hash.update([0]);
    for part in parts {
        hash.update((part.len() as u64).to_be_bytes());
        hash.update(part);
    }
    format!("{HASH_PREFIX}{}", hex(&hash.finalize()))
}

pub(crate) fn hash_bytes(tag: &[u8], bytes: &[u8]) -> String {
    fingerprint_parts(std::str::from_utf8(tag).unwrap_or("review-hash"), [bytes])
}

fn canonical_json(value: &Value) -> Result<Value> {
    match value {
        Value::Object(object) => {
            let sorted: BTreeMap<&String, Value> = object
                .iter()
                .map(|(key, value)| Ok((key, canonical_json(value)?)))
                .collect::<Result<_>>()?;
            let mut result = Map::new();
            for (key, value) in sorted {
                result.insert(key.clone(), value);
            }
            Ok(Value::Object(result))
        }
        Value::Array(items) => Ok(Value::Array(
            items.iter().map(canonical_json).collect::<Result<_>>()?,
        )),
        scalar => Ok(scalar.clone()),
    }
}

fn normalized_frontmatter(frontmatter: &YamlValue) -> Result<Value> {
    let YamlValue::Mapping(mapping) = frontmatter else {
        return Err(anyhow!("plan frontmatter must be a YAML mapping"));
    };
    let mut fields = BTreeMap::new();
    for (key, value) in mapping {
        let Some(key) = key.as_str() else {
            return Err(anyhow!("plan frontmatter keys must be strings"));
        };
        if key == "status" {
            continue;
        }
        let timestamp_context = if key == "provenance" {
            TimestampContext::Provenance
        } else {
            TimestampContext::None
        };
        if let Some(value) = yaml_to_json(value, timestamp_context)? {
            fields.insert(key.to_string(), value);
        }
    }
    let mut result = Map::new();
    for (key, value) in fields {
        result.insert(key, value);
    }
    Ok(Value::Object(result))
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum TimestampContext {
    None,
    Provenance,
    Generated,
}

fn yaml_to_json(value: &YamlValue, timestamp_context: TimestampContext) -> Result<Option<Value>> {
    let value = match value {
        YamlValue::Null => Value::Null,
        YamlValue::Bool(value) => Value::Bool(*value),
        YamlValue::Number(value) => serde_json::to_value(value)?,
        YamlValue::String(value) => Value::String(value.clone()),
        YamlValue::Sequence(values) => {
            let mut normalized = Vec::with_capacity(values.len());
            for value in values {
                if let Some(value) = yaml_to_json(value, timestamp_context)? {
                    normalized.push(value);
                }
            }
            Value::Array(normalized)
        }
        YamlValue::Mapping(values) => {
            let mut sorted = BTreeMap::new();
            for (key, value) in values {
                let Some(key) = key.as_str() else {
                    return Err(anyhow!("plan frontmatter keys must be strings"));
                };
                if is_generated_timestamp(timestamp_context, key) {
                    continue;
                }
                let child_context =
                    if timestamp_context == TimestampContext::Provenance && key == "generated" {
                        TimestampContext::Generated
                    } else {
                        timestamp_context
                    };
                if let Some(value) = yaml_to_json(value, child_context)? {
                    sorted.insert(key.to_string(), value);
                }
            }
            let mut object = Map::new();
            for (key, value) in sorted {
                object.insert(key, value);
            }
            Value::Object(object)
        }
        YamlValue::Tagged(_) => {
            return Err(anyhow!(
                "tagged YAML values are not supported in plan frontmatter"
            ));
        }
    };
    Ok(Some(value))
}

fn is_generated_timestamp(context: TimestampContext, key: &str) -> bool {
    match context {
        TimestampContext::None => false,
        TimestampContext::Provenance => {
            matches!(
                key,
                "timestamp" | "created_at" | "updated_at" | "generated_at"
            ) || key.ends_with("_at")
        }
        TimestampContext::Generated => {
            matches!(
                key,
                "at" | "timestamp" | "created_at" | "updated_at" | "generated_at"
            ) || key.ends_with("_at")
        }
    }
}

fn normalize_markdown_body(body: &str) -> String {
    let mut normalizer = MarkdownBodyNormalizer::default();
    for raw_line in body.replace("\r\n", "\n").replace('\r', "\n").split('\n') {
        normalizer.consume_line(raw_line);
    }
    normalizer.finish()
}

#[derive(Default)]
struct MarkdownBodyNormalizer {
    output: Vec<String>,
    paragraph: Vec<String>,
    list_content_columns: Vec<usize>,
    fence: Option<(char, usize)>,
    excluded_section: Option<usize>,
    acceptance_section: Option<usize>,
    in_acceptance: bool,
    blank_pending: bool,
}

impl MarkdownBodyNormalizer {
    fn consume_line(&mut self, line: &str) {
        if let Some((marker, width)) = self.fence {
            self.consume_fence_line(line, marker, width);
            return;
        }
        if line.trim().is_empty() {
            self.consume_blank_line();
            return;
        }

        let (_, indentation) = indentation_columns(line);
        let list_item = list_item_layout(line);
        while self
            .list_content_columns
            .last()
            .is_some_and(|content_column| indentation < *content_column)
        {
            self.list_content_columns.pop();
        }
        let parent_content_column = self
            .list_content_columns
            .last()
            .copied()
            .unwrap_or_default();
        if indentation.saturating_sub(parent_content_column) >= 4 {
            self.consume_indented_code(line);
            return;
        }

        if let Some((marker, width)) = fence_start(line) {
            self.start_fence(line, marker, width);
            return;
        }

        if let Some((level, title)) = heading(line) {
            self.consume_heading(level, title);
            return;
        }
        if self.excluded_section.is_some() {
            return;
        }

        if let Some(layout) = list_item {
            self.flush_paragraph();
            self.push_pending_blank();
            self.output
                .push(normalize_list_item(line, self.in_acceptance, layout));
            self.list_content_columns.push(layout.content_column);
            return;
        }
        let trimmed = line.trim();
        if trimmed.starts_with('>') || trimmed.starts_with('|') || is_horizontal_rule(trimmed) {
            self.flush_paragraph();
            self.push_pending_blank();
            self.output.push(normalize_inline_code_whitespace(trimmed));
            return;
        }
        self.paragraph.push(line.to_string());
    }

    fn consume_fence_line(&mut self, line: &str, marker: char, width: usize) {
        if self.excluded_section.is_none() {
            self.output.push(line.to_string());
        }
        if fence_end(line.trim_start(), marker, width) {
            self.fence = None;
        }
        self.blank_pending = false;
    }

    fn consume_blank_line(&mut self) {
        if self.excluded_section.is_none() {
            self.flush_paragraph();
            self.blank_pending = !self.output.is_empty();
        }
    }

    fn consume_indented_code(&mut self, line: &str) {
        if self.excluded_section.is_none() {
            self.flush_paragraph();
            self.push_pending_blank();
            self.output.push(line.to_string());
        }
    }

    fn start_fence(&mut self, line: &str, marker: char, width: usize) {
        self.flush_paragraph();
        if self.excluded_section.is_none() {
            self.push_pending_blank();
        }
        self.fence = Some((marker, width));
        if self.excluded_section.is_none() {
            self.output.push(line.to_string());
        }
    }

    fn consume_heading(&mut self, level: usize, title: &str) {
        self.list_content_columns.clear();
        if self
            .excluded_section
            .is_some_and(|excluded| level <= excluded)
        {
            self.excluded_section = None;
        }
        if self
            .acceptance_section
            .is_some_and(|acceptance| level <= acceptance)
        {
            self.acceptance_section = None;
        }
        let normalized_title = normalize_inline_code_whitespace(title);
        if matches!(
            normalized_title.to_ascii_lowercase().as_str(),
            "progress" | "related"
        ) {
            self.excluded_section = Some(level);
        }
        if normalized_title.eq_ignore_ascii_case("acceptance criteria") {
            self.acceptance_section = Some(level);
        }
        self.in_acceptance = self.acceptance_section.is_some();
        self.flush_paragraph();
        if self.excluded_section.is_some() {
            return;
        }
        self.push_pending_blank();
        self.output
            .push(format!("{} {}", "#".repeat(level), normalized_title));
    }

    fn flush_paragraph(&mut self) {
        if !self.paragraph.is_empty() {
            self.output
                .push(normalize_inline_code_whitespace(&self.paragraph.join("\n")));
            self.paragraph.clear();
            self.blank_pending = false;
        }
    }

    fn push_pending_blank(&mut self) {
        push_pending_blank(&mut self.output, &mut self.blank_pending);
    }

    fn finish(mut self) -> String {
        self.flush_paragraph();
        while self.output.last().is_some_and(String::is_empty) {
            self.output.pop();
        }
        self.output.join("\n")
    }
}

fn heading(line: &str) -> Option<(usize, &str)> {
    let trimmed = line.trim_start();
    let level = trimmed.bytes().take_while(|byte| *byte == b'#').count();
    if !(1..=6).contains(&level) {
        return None;
    }
    let rest = &trimmed[level..];
    let has_open_separator = rest
        .as_bytes()
        .first()
        .is_some_and(|byte| matches!(byte, b' ' | b'\t'));
    if !rest.is_empty() && !has_open_separator {
        return None;
    }
    let title = rest.trim_matches([' ', '\t']);
    let trailing_hashes = title.bytes().rev().take_while(|byte| *byte == b'#').count();
    let title = if trailing_hashes > 0 {
        let marker_start = title.len() - trailing_hashes;
        let before_marker = &title[..marker_start];
        if before_marker
            .as_bytes()
            .last()
            .is_some_and(|byte| matches!(byte, b' ' | b'\t'))
            || (marker_start == 0 && has_open_separator)
        {
            before_marker.trim_end_matches([' ', '\t'])
        } else {
            title
        }
    } else {
        title
    };
    Some((level, title))
}

#[derive(Clone, Copy)]
struct ListItemLayout {
    marker_start: usize,
    marker_end: usize,
    content_column: usize,
}

fn normalize_list_item(line: &str, in_acceptance: bool, layout: ListItemLayout) -> String {
    let indent = &line[..layout.marker_start];
    let marker = &line[layout.marker_start..layout.marker_end];
    let text = line[layout.marker_end..].trim();
    if in_acceptance
        && let Some(after) = text
            .strip_prefix("[ ]")
            .or_else(|| text.strip_prefix("[x]"))
            .or_else(|| text.strip_prefix("[X]"))
    {
        return format!(
            "{indent}{marker} [ ] {}",
            normalize_inline_code_whitespace(after.trim_start())
        );
    }
    format!(
        "{indent}{marker} {}",
        normalize_inline_code_whitespace(text)
    )
}

fn list_item_layout(line: &str) -> Option<ListItemLayout> {
    let (marker_start, indentation) = indentation_columns(line);
    let rest = &line[marker_start..];
    let marker_len = if rest.starts_with(['-', '+', '*']) {
        1
    } else {
        let digits = rest.bytes().take_while(u8::is_ascii_digit).count();
        if digits > 0
            && rest
                .as_bytes()
                .get(digits)
                .is_some_and(|byte| matches!(byte, b'.' | b')'))
        {
            digits + 1
        } else {
            return None;
        }
    };
    if !rest
        .as_bytes()
        .get(marker_len)
        .is_some_and(|byte| matches!(byte, b' ' | b'\t'))
    {
        return None;
    }
    let after_marker = &rest[marker_len..];
    let whitespace_len = after_marker
        .bytes()
        .take_while(|byte| matches!(byte, b' ' | b'\t'))
        .count();
    let marker_column = indentation + marker_len;
    let actual_content_column = advance_columns(marker_column, &after_marker[..whitespace_len]);
    let actual_padding = actual_content_column - marker_column;
    let padding = if (1..=4).contains(&actual_padding) {
        actual_padding
    } else {
        1
    };
    Some(ListItemLayout {
        marker_start,
        marker_end: marker_start + marker_len,
        content_column: marker_column + padding,
    })
}

fn indentation_columns(line: &str) -> (usize, usize) {
    let mut bytes = 0;
    let mut columns = 0;
    for character in line.chars() {
        match character {
            ' ' => columns += 1,
            '\t' => columns = (columns / 4 + 1) * 4,
            _ => break,
        }
        bytes += character.len_utf8();
    }
    (bytes, columns)
}

fn advance_columns(start: usize, whitespace: &str) -> usize {
    let mut columns = start;
    for character in whitespace.chars() {
        match character {
            ' ' => columns += 1,
            '\t' => columns = (columns / 4 + 1) * 4,
            _ => break,
        }
    }
    columns
}

fn normalize_inline_code_whitespace(value: &str) -> String {
    let mut output = String::new();
    let mut pending_space = false;
    let mut cursor = 0;
    while let Some(relative_start) = value[cursor..].find('`') {
        let start = cursor + relative_start;
        if is_escaped(value, start) {
            append_normalized_prose(&mut output, &value[cursor..=start], &mut pending_space);
            cursor = start + 1;
            continue;
        }

        append_normalized_prose(&mut output, &value[cursor..start], &mut pending_space);
        let delimiter_end = backtick_run_end(value, start);
        let delimiter_width = delimiter_end - start;
        let Some(code_end) = matching_backtick_run_end(value, delimiter_end, delimiter_width)
        else {
            append_normalized_prose(
                &mut output,
                &value[start..delimiter_end],
                &mut pending_space,
            );
            cursor = delimiter_end;
            continue;
        };

        if pending_space && !output.is_empty() {
            output.push(' ');
        }
        pending_space = false;
        output.push_str(&value[start..code_end]);
        cursor = code_end;
    }
    append_normalized_prose(&mut output, &value[cursor..], &mut pending_space);
    output
}

fn append_normalized_prose(output: &mut String, prose: &str, pending_space: &mut bool) {
    for character in prose.chars() {
        if character.is_whitespace() {
            *pending_space = true;
            continue;
        }
        if *pending_space && !output.is_empty() {
            output.push(' ');
        }
        *pending_space = false;
        output.push(character);
    }
}

fn is_escaped(value: &str, position: usize) -> bool {
    let backslashes = value[..position]
        .bytes()
        .rev()
        .take_while(|byte| *byte == b'\\')
        .count();
    backslashes % 2 == 1
}

fn backtick_run_end(value: &str, start: usize) -> usize {
    value[start..]
        .bytes()
        .take_while(|byte| *byte == b'`')
        .count()
        + start
}

fn matching_backtick_run_end(value: &str, mut cursor: usize, width: usize) -> Option<usize> {
    while cursor < value.len() {
        let next = value[cursor..].find('`')? + cursor;
        let end = backtick_run_end(value, next);
        if end - next == width {
            return Some(end);
        }
        cursor = end;
    }
    None
}

fn fence_start(line: &str) -> Option<(char, usize)> {
    let trimmed = line.trim_start();
    let marker = trimmed.chars().next()?;
    if marker != '`' && marker != '~' {
        return None;
    }
    let width = trimmed
        .chars()
        .take_while(|character| *character == marker)
        .count();
    (width >= 3).then_some((marker, width))
}

fn fence_end(line: &str, marker: char, width: usize) -> bool {
    let count = line
        .chars()
        .take_while(|character| *character == marker)
        .count();
    count >= width && line[count..].trim().is_empty()
}

fn is_horizontal_rule(line: &str) -> bool {
    let compact = line
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect::<String>();
    ["---", "***", "___"].iter().any(|rule| {
        compact.len() >= 3
            && compact
                .chars()
                .all(|character| character == rule.chars().next().unwrap())
    })
}

fn push_pending_blank(output: &mut Vec<String>, blank_pending: &mut bool) {
    if *blank_pending && !output.last().is_some_and(String::is_empty) {
        output.push(String::new());
    }
    *blank_pending = false;
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn markdown_normalization_preserves_mixed_section_boundaries() {
        let body = "\r\n## Acceptance criteria\r\n- [x] One  thing\r\n\r\n```text\r\n  literal  \r\n```\r\n## Progress\r\nignore\r\n## Problem\r\nA \t B\r\n";
        assert_eq!(
            normalize_markdown_body(body),
            "## Acceptance criteria\n- [ ] One thing\n\n```text\n  literal  \n```\n## Problem\nA B"
        );
    }

    #[test]
    fn plan_fingerprint_ignores_lifecycle_and_formatting_but_keeps_structure() {
        let first = b"---\ntype: plan\nstatus: backlog\nprovenance:\n  generated:\n    by: tool\n    at: 2026-09-26T10:00:00Z\n---\n## Problem\nTwo lines\nof prose.\n\n## Acceptance criteria\n- [ ] Works\n\n## Progress\nold\n";
        let equivalent = b"---\nstatus: active\ntype: plan\nprovenance:\n  generated:\n    by: tool\n    at: 2026-09-27T10:00:00Z\n---\n## Problem\nTwo lines of prose.\n\n## Acceptance criteria\n- [x] Works\n\n## Progress\nnew\n";
        let changed = b"---\ntype: plan\nstatus: active\n---\n## Problem\nTwo lines of prose.\n\n## Acceptance criteria\n- [x] Changed\n";
        assert_eq!(
            contract_fingerprint(first).unwrap(),
            contract_fingerprint(equivalent).unwrap()
        );
        assert_ne!(
            contract_fingerprint(first).unwrap(),
            contract_fingerprint(changed).unwrap()
        );
    }

    #[test]
    fn code_and_nested_list_structure_remain_in_fingerprint() {
        let first = b"---\ntype: plan\n---\n- parent\n  - child\n\n```text\n  x  \n```\n";
        let changed_list = b"---\ntype: plan\n---\n- parent\n    - child\n\n```text\n  x  \n```\n";
        let changed_code = b"---\ntype: plan\n---\n- parent\n  - child\n\n```text\nx\n```\n";
        assert_ne!(
            contract_fingerprint(first).unwrap(),
            contract_fingerprint(changed_list).unwrap()
        );
        assert_ne!(
            contract_fingerprint(first).unwrap(),
            contract_fingerprint(changed_code).unwrap()
        );
    }

    #[test]
    fn excluded_progress_fences_do_not_leak_headings_or_content() {
        let first = b"---\ntype: plan\n---\n## Progress\n```md\n## Solution\nold progress\n```\n## Solution\nkeep this\n";
        let changed_progress = b"---\ntype: plan\n---\n## Progress\n```md\n## Other\nnew progress\n```\n## Solution\nkeep this\n";
        let changed_contract = b"---\ntype: plan\n---\n## Progress\n```md\n## Other\nnew progress\n```\n## Solution\nchanged this\n";
        assert_eq!(
            contract_fingerprint(first).unwrap(),
            contract_fingerprint(changed_progress).unwrap()
        );
        assert_ne!(
            contract_fingerprint(first).unwrap(),
            contract_fingerprint(changed_contract).unwrap()
        );
    }

    #[test]
    fn indented_code_heading_is_not_treated_as_a_section() {
        let first = b"---\ntype: plan\n---\n## Problem\n    ## Progress\n    meaningful code\n";
        let changed = b"---\ntype: plan\n---\n## Problem\n    ## Progress\n    changed code\n";
        assert_ne!(
            contract_fingerprint(first).unwrap(),
            contract_fingerprint(changed).unwrap()
        );
    }
}
