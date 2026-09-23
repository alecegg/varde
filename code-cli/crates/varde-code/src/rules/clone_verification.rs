//! Source verification for exact clone rules.

use crate::parse::{language_for_path, parse_source_for_path};
use crate::rules::finding::{Finding, finding_id};
use crate::rules::{Diagnostic, Rule};
use ast_grep_core::Node;
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

const DEFAULT_MIN_TOKENS: usize = 20;
const DEFAULT_MIN_MEMBERS: usize = 3;
const DEFAULT_MIN_LINES: usize = 8;

type CloneGroups = BTreeMap<Vec<u8>, (usize, Vec<Finding>)>;
struct CloneSource {
    text: String,
    parsed: crate::parse::ParsedFile,
}

/// Verify SQL candidate rows against source trees.
pub fn verify(
    rule: &Rule,
    root: &Path,
    candidates: Vec<Finding>,
) -> (Vec<Finding>, Vec<Diagnostic>) {
    let budgets = match thresholds(rule) {
        Ok(values) => values,
        Err(reason) => return (Vec::new(), vec![diag(rule, "", &reason)]),
    };
    let (min_tokens, _, min_lines) = budgets;
    let mut diagnostics = Vec::new();
    let mut sources = BTreeMap::new();
    let mut groups = CloneGroups::new();
    for finding in candidates {
        let path = resolve_path(root, &finding.location.file);
        let source = sources
            .entry(path.clone())
            .or_insert_with(|| match read_source(&path) {
                Ok(source) => Some(source),
                Err(reason) => {
                    diagnostics.push(diag(rule, &finding.location.file, &reason));
                    None
                }
            });
        let Some(source) = source else { continue };
        let (canonical, tokens) = match candidate_tree(source, &finding) {
            Ok(tree) => tree,
            Err(reason) => {
                diagnostics.push(diag(rule, &finding.location.file, reason));
                continue;
            }
        };
        if tokens < min_tokens
            || finding
                .location
                .span
                .end_line
                .saturating_sub(finding.location.span.start_line)
                < min_lines as u32
        {
            continue;
        }
        groups
            .entry(canonical)
            .or_insert_with(|| (tokens, Vec::new()))
            .1
            .push(finding);
    }
    (group_findings(groups, budgets), diagnostics)
}

fn read_source(path: &Path) -> Result<CloneSource, String> {
    let lang = language_for_path(path).ok_or("unsupported clone source")?;
    let text = fs::read_to_string(path).map_err(|error| format!("source read failed: {error}"))?;
    let parsed = parse_source_for_path(&lang, path, &text);
    if parsed.has_error() {
        return Err("clone source has parse errors".into());
    }
    Ok(CloneSource { text, parsed })
}

fn candidate_tree(
    source: &CloneSource,
    finding: &Finding,
) -> Result<(Vec<u8>, usize), &'static str> {
    let node = find_span(
        source.parsed.root.root(),
        finding.location.span.start_byte as usize,
        finding.location.span.end_byte as usize,
    )
    .ok_or("function span missing from source tree")?;
    let mut canonical = format!("L:{:?};", source.parsed.lang).into_bytes();
    let mut tokens = 0;
    canonicalize(body_node(node), &source.text, &mut canonical, &mut tokens);
    Ok((canonical, tokens))
}

fn group_findings(groups: CloneGroups, budgets: (usize, usize, usize)) -> Vec<Finding> {
    let (min_tokens, min_members, min_lines) = budgets;
    let mut output = Vec::new();
    for (canonical, (tokens, mut members)) in groups {
        members.sort_by_key(member_key);
        members.dedup_by(|a, b| member_key(a) == member_key(b));
        if members.len() < min_members {
            continue;
        }
        let group = format!(
            "exact-clone-{:016x}:{}:{}",
            stable_hash(&canonical),
            members[0].location.file,
            members[0].location.span.start_byte
        );
        let locations: Vec<_> = members.iter().map(|m| serde_json::json!({
            "file": m.location.file, "startLine": m.location.span.start_line, "endLine": m.location.span.end_line,
        })).collect();
        for mut finding in members {
            finding.evidence = serde_json::json!({ "verification": "exact-clone", "group": group, "label": group, "members": locations, "token_count": tokens, "min_tokens": min_tokens, "min_members": min_members, "min_span_lines": min_lines });
            finding.id = finding_id(
                &finding.rule_id,
                &finding.location.file,
                &finding.location.span,
            );
            output.push(finding);
        }
    }
    output.sort_by_key(member_key);
    output
}

/// Reject invalid policy budgets before execution, including empty candidate sets.
pub(super) fn thresholds(rule: &Rule) -> Result<(usize, usize, usize), String> {
    let value = |name: &str, default: usize, minimum: usize| -> Result<usize, String> {
        let raw = rule
            .thresholds
            .as_ref()
            .and_then(|m| m.get(name))
            .copied()
            .unwrap_or(default as f64);
        if !raw.is_finite() || raw.fract() != 0.0 || raw < minimum as f64 || raw > u32::MAX as f64 {
            return Err(format!(
                "{name} must be an integer between {minimum} and {}",
                u32::MAX
            ));
        }
        Ok(raw as usize)
    };
    Ok((
        value("min_tokens", DEFAULT_MIN_TOKENS, 1)?,
        value("min_members", DEFAULT_MIN_MEMBERS, 2)?,
        value("min_span_lines", DEFAULT_MIN_LINES, 0)?,
    ))
}

fn stable_hash(bytes: &[u8]) -> u64 {
    bytes.iter().fold(0xcbf29ce484222325, |h, b| {
        (h ^ u64::from(*b)).wrapping_mul(0x100000001b3)
    })
}

fn resolve_path(root: &Path, path: &str) -> PathBuf {
    let path = Path::new(path);
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        root.join(path)
    }
}

fn member_key(f: &Finding) -> (String, u32, u32) {
    (
        f.location.file.clone(),
        f.location.span.start_byte,
        f.location.span.end_byte,
    )
}

fn diag(rule: &Rule, file: &str, reason: &str) -> Diagnostic {
    Diagnostic {
        rule_id: Some(rule.id.clone()),
        file: file.to_string(),
        reason: reason.to_string(),
    }
}

fn find_span<'a>(
    node: Node<'a, StrDoc<SupportLang>>,
    start: usize,
    end: usize,
) -> Option<Node<'a, StrDoc<SupportLang>>> {
    if node.range().start == start && node.range().end == end {
        return Some(node);
    }
    node.children().find_map(|child| {
        (child.range().start <= start && child.range().end >= end)
            .then(|| find_span(child, start, end))
            .flatten()
    })
}

fn body_node<'a>(node: Node<'a, StrDoc<SupportLang>>) -> Node<'a, StrDoc<SupportLang>> {
    const BODY_KINDS: &[&str] = &[
        "body",
        "block",
        "compound_statement",
        "statement_block",
        "suite",
        "do_block",
        "expression_body",
        "function_body",
    ];
    let body = node.children().find(|child| {
        child.is_named() && BODY_KINDS.iter().any(|kind| child.kind().as_ref() == *kind)
    });
    body.unwrap_or(node)
}

fn canonicalize(
    node: Node<'_, StrDoc<SupportLang>>,
    source: &str,
    out: &mut Vec<u8>,
    tokens: &mut usize,
) {
    if node.is_extra() {
        return;
    }
    let kind = node.kind();
    out.extend_from_slice(b"N");
    out.extend_from_slice(&(kind.len() as u32).to_le_bytes());
    out.extend_from_slice(kind.as_bytes());
    let children: Vec<_> = node.children().collect();
    if children.is_empty() {
        let text = &source[node.range().start..node.range().end];
        out.extend_from_slice(b"T");
        out.extend_from_slice(&(text.len() as u32).to_le_bytes());
        out.extend_from_slice(text.as_bytes());
        *tokens += 1;
    } else {
        for child in children {
            canonicalize(child, source, out, tokens);
        }
    }
    out.extend_from_slice(b"E");
}
