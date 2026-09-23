//! `scan` orchestration: tie the rule-pack loader and both rule engines
//! together into one read-and-report flow.
//!
//! Flow: build or refresh the index against the working tree →
//! open the persisted DB read-only →
//! `load_rules(repo_root)` → dispatch `kind=pattern` rules over the source
//! tree and `kind=sql` rules against the connection → merge findings and
//! rule/source diagnostics into `{ findings, diagnostics, gate }`.
//!
//! Named `scan_cli` (distinct from `scan`, the low-level file-listing
//! module this flow reuses for the pattern-rule file set).

use crate::query::ApiError;
use crate::rules::Severity;
use crate::rules::rewrite::{RewriteStatus, RewriteTarget};
use std::collections::{BTreeMap, HashMap};
use std::path::Path;

const DEFAULT_FINDINGS_LIMIT: usize = 100;

/// Required `repoRoot` from the input, validated to be an existing directory.
/// Shared by the rule-pack management endpoints (`rules_list`/`rules_seed`/
/// `rules_remove`), which all take the same `{ repoRoot }` shape before doing
/// their own thing with it.
fn require_repo_dir(input: &serde_json::Value) -> Result<&Path, ApiError> {
    let repo_root = crate::query::req_str(input, "repoRoot")?;
    let repo_path = Path::new(repo_root);
    if !repo_path.is_dir() {
        return Err(ApiError::new(
            "invalid_input",
            format!("repoRoot is not a directory: {repo_root}"),
        ));
    }
    Ok(repo_path)
}

/// Resolve `severityThreshold` from the scan input (default `"error"`).
pub fn severity_threshold(input: &serde_json::Value) -> Result<Severity, ApiError> {
    let Some(value) = input.get("severityThreshold") else {
        return Ok(Severity::Error);
    };
    let Some(name) = value.as_str() else {
        return Err(ApiError::new(
            "invalid_input",
            "severityThreshold must be a string (expected error|warning|info)",
        ));
    };
    Severity::from_name(name).ok_or_else(|| {
        ApiError::new(
            "invalid_input",
            format!("unknown severityThreshold {name:?} (expected error|warning|info)"),
        )
    })
}

/// Whether any finding's severity meets or exceeds `threshold`.
///
/// Findings carry a lowercase severity name; a missing/unparseable severity
/// is treated as `Info` (the lowest rank), so it can never trip a threshold.
pub fn findings_at_or_above(payload: &serde_json::Value, threshold: Severity) -> bool {
    payload
        .get("findings")
        .and_then(|f| f.as_array())
        .into_iter()
        .flatten()
        .any(|f| {
            // A missing/unparseable severity is not a finding the threshold
            // can trip on.
            f.get("severity")
                .and_then(|s| s.as_str())
                .and_then(Severity::from_name)
                .is_some_and(|severity| severity >= threshold)
        })
}

/// Whether any *unresolved* finding's severity meets or exceeds `threshold`.
///
/// `--apply` exit-code gate: a finding whose `rewrite_status` is `"applied"`
/// was fixed in place and no longer blocks the CI gate; every other finding
/// (skipped-dirty/overlap/conflict, or any finding with no rewrite status at
/// all — SQL rules, rewrite-less pattern rules, non-apply runs) gates
/// exactly as before. Non-apply runs emit no `rewrite_status`, so this is
/// identical to `findings_at_or_above` for them.
pub fn unresolved_findings_at_or_above(payload: &serde_json::Value, threshold: Severity) -> bool {
    unresolved_finding_count(payload, threshold) > 0
}

fn unresolved_finding_count(payload: &serde_json::Value, threshold: Severity) -> usize {
    payload
        .get("findings")
        .and_then(|f| f.as_array())
        .into_iter()
        .flatten()
        .filter(|f| f.get("rewrite_status").and_then(|s| s.as_str()) != Some("applied"))
        .filter(|f| {
            f.get("severity")
                .and_then(|s| s.as_str())
                .and_then(Severity::from_name)
                .is_some_and(|severity| severity >= threshold)
        })
        .count()
}

/// Run the scan flow for `{ repoRoot, ... }` and return the merged
/// `{ findings, diagnostics }` payload.
///
/// Tool-level failures during index refresh or database access, or an
/// unreadable repo root, are whole-flow `ApiError`s (the CLI renders
/// the `{ok:false,data:{error},meta}` envelope and exits non-zero). An empty rule pack
/// is a valid no-op scan: `Ok` with empty arrays.
///
/// `apply: true` (from the `--apply` CLI flag) additionally runs the
/// rewrite machinery over pattern-rule findings that carry a `rewrite`
/// template: per-file git-clean gating (unless `force`), span planning,
/// atomic writes. Findings from rules without a `rewrite` template are
/// never written and never git-gated.
pub fn scan_repo(input: &serde_json::Value) -> Result<serde_json::Value, ApiError> {
    let (repo_path, apply, force, findings_options) = scan_options(input)?;
    let (rules, rule_diagnostics, origins) = crate::rules::load_rules_with_origins(repo_path);
    let gate_rules = selected_gate_rules(input, &rules)?;
    let threshold = severity_threshold(input)?;
    crate::query::freshen_for_mode("scan", input)?;
    let conn = open_scan_db(repo_path)?;
    let (rules, findings, diagnostics) = run_scan_rules(repo_path, &conn, rules, rule_diagnostics)?;
    let (findings, stale_suppressions) =
        crate::rules::suppress::filter_findings(filter_generated(findings), repo_path);
    // An incomplete scan cannot safely rewrite source. Keep the findings and
    // diagnostics in the successful result so callers can repair the cause.
    let complete = diagnostics
        .iter()
        .all(|diagnostic| !blocks_gate(diagnostic));
    let statuses = if apply && complete {
        apply_rewrites(&rules, &findings, repo_path, force)?
    } else {
        HashMap::new()
    };
    let rewrite_count = rewrite_bearing_count(&rules, &findings);
    let mut payload = build_scan_payload(findings, diagnostics, stale_suppressions);
    if apply && complete {
        attach_rewrite_statuses(&mut payload, &statuses, rewrite_count);
    }
    attach_gate(&mut payload, threshold, gate_rules.as_deref());
    attach_policy(
        &mut payload,
        &rules,
        &origins,
        threshold,
        gate_rules.as_deref(),
    );
    attach_findings_summary(&mut payload);
    hoist_rule_legend(&mut payload, &rules);
    truncate_findings(&mut payload, findings_options);
    crate::query::output::postprocess(&mut payload, input);
    Ok(payload)
}

fn selected_gate_rules(
    input: &serde_json::Value,
    rules: &[crate::rules::Rule],
) -> Result<Option<Vec<String>>, ApiError> {
    let Some(selection) = input.get("gateRules") else {
        return Ok(None);
    };
    if input.get("severityThreshold").is_some() {
        return Err(ApiError::new(
            "invalid_input",
            "gateRules and severityThreshold are mutually exclusive",
        ));
    }
    let ids = selection
        .as_array()
        .filter(|ids| !ids.is_empty())
        .ok_or_else(|| {
            ApiError::new(
                "invalid_input",
                "gateRules must be a nonempty array of rule IDs",
            )
        })?;
    let mut selected = Vec::with_capacity(ids.len());
    for id in ids {
        let id = id.as_str().ok_or_else(|| {
            ApiError::new("invalid_input", "gateRules entries must be rule ID strings")
        })?;
        if !rules.iter().any(|rule| rule.id == id) {
            return Err(ApiError::new(
                "invalid_input",
                format!("unknown active gate rule: {id}"),
            ));
        }
        let rule = rules
            .iter()
            .find(|rule| rule.id == id)
            .expect("active rule checked");
        if !crate::rules::boundary_configured(rule)
            .map_err(|reason| ApiError::new("invalid_input", reason))?
        {
            return Err(ApiError::new(
                "invalid_input",
                format!("gate rule {id} requires source_prefix and target_prefix configuration"),
            ));
        }
        if selected.iter().any(|previous| previous == id) {
            return Err(ApiError::new(
                "invalid_input",
                format!("duplicate gate rule: {id}"),
            ));
        }
        selected.push(id.to_owned());
    }
    selected.sort();
    Ok(Some(selected))
}

fn scan_options(
    input: &serde_json::Value,
) -> Result<(&Path, bool, bool, FindingsOptions), ApiError> {
    if !input.is_object() {
        return Err(ApiError::new(
            "invalid_input",
            "scan input must be a JSON object",
        ));
    }
    let repo_root = crate::query::req_str(input, "repoRoot")?;
    let repo_path = Path::new(repo_root);
    if !repo_path.is_dir() {
        return Err(ApiError::new(
            "invalid_input",
            format!("repoRoot is not a directory: {repo_root}"),
        ));
    }
    let flag = |name| -> Result<bool, ApiError> {
        match input.get(name) {
            None => Ok(false),
            Some(value) => value
                .as_bool()
                .ok_or_else(|| ApiError::new("invalid_input", format!("{name} must be a boolean"))),
        }
    };
    let apply = flag("apply")?;
    let force = flag("force")?;
    severity_threshold(input)?;
    let findings_options = findings_options(input)?;
    if input.get("output").is_some_and(|value| !value.is_string()) {
        return Err(ApiError::new("invalid_input", "output must be a string"));
    }
    Ok((repo_path, apply, force, findings_options))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FindingsOptions {
    full: bool,
    limit: usize,
    offset: usize,
}

fn findings_options(input: &serde_json::Value) -> Result<FindingsOptions, ApiError> {
    let full = match input.get("fullFindings") {
        None => false,
        Some(value) => value
            .as_bool()
            .ok_or_else(|| ApiError::new("invalid_input", "fullFindings must be a boolean"))?,
    };
    let number = |name: &str| -> Result<Option<usize>, ApiError> {
        let Some(value) = input.get(name) else {
            return Ok(None);
        };
        let number = value.as_u64().ok_or_else(|| {
            ApiError::new(
                "invalid_input",
                format!("{name} must be a nonnegative integer"),
            )
        })?;
        usize::try_from(number).map(Some).map_err(|_| {
            ApiError::new(
                "invalid_input",
                format!("{name} is too large for this platform"),
            )
        })
    };
    let limit = number("findingsLimit")?.unwrap_or(DEFAULT_FINDINGS_LIMIT);
    if limit == 0 {
        return Err(ApiError::new(
            "invalid_input",
            "findingsLimit must be greater than zero",
        ));
    }
    Ok(FindingsOptions {
        full,
        limit,
        offset: number("findingsOffset")?.unwrap_or(0),
    })
}

fn open_scan_db(repo_path: &Path) -> Result<rusqlite::Connection, ApiError> {
    let db_path = crate::db::path::repo_db_path(repo_path);
    crate::db::open_read_only(&db_path).map_err(|error| {
        ApiError::new(
            "db_error",
            format!(
                "database unavailable at {}: {error}; run `varde-code build --repo-root {}` first",
                db_path.display(),
                repo_path.display()
            ),
        )
    })
}

type ScanResults = (
    Vec<crate::rules::Rule>,
    Vec<crate::rules::finding::Finding>,
    Vec<serde_json::Value>,
);

fn run_scan_rules(
    repo_path: &Path,
    conn: &rusqlite::Connection,
    rules: Vec<crate::rules::Rule>,
    rule_diagnostics: Vec<crate::rules::Diagnostic>,
) -> Result<ScanResults, ApiError> {
    let mut diagnostics: Vec<serde_json::Value> = rule_diagnostics
        .into_iter()
        .map(|diagnostic| serde_json::to_value(diagnostic).expect("rule diagnostic serializes"))
        .collect();
    let (mut findings, mut pattern_diagnostics) =
        crate::rules::pattern::run_pattern_rules(&rules, repo_path, conn)?;
    let (sql_findings, mut sql_diagnostics) =
        crate::rules::sql::run_sql_rules_in_repo(&rules, conn, repo_path)?;
    findings.extend(sql_findings);
    diagnostics.extend(pattern_diagnostics.drain(..).map(|diagnostic| {
        serde_json::to_value(diagnostic).expect("pattern diagnostic serializes")
    }));
    diagnostics.extend(
        sql_diagnostics
            .drain(..)
            .map(|diagnostic| serde_json::to_value(diagnostic).expect("SQL diagnostic serializes")),
    );
    diagnostics.extend(persisted_diagnostics(conn)?);
    for diagnostic in &mut diagnostics {
        normalize_diagnostic(diagnostic);
    }
    Ok((rules, findings, diagnostics))
}

fn persisted_diagnostics(conn: &rusqlite::Connection) -> Result<Vec<serde_json::Value>, ApiError> {
    let mut statement = conn
        .prepare(
            "SELECT d.file_id, d.path, d.message, d.severity, \
             COALESCE(f.is_test_path, 0) \
             FROM diagnostics d LEFT JOIN files f ON f.id = d.file_id \
             ORDER BY d.id",
        )
        .map_err(crate::query::db_err)?;
    let rows = statement
        .query_map([], |row| {
            let message = row.get::<_, String>(2)?;
            if is_expected_source_skip(&message) {
                return Ok(None);
            }
            Ok(Some(serde_json::json!({
                "source": "persisted",
                "file_id": row.get::<_, Option<i64>>(0)?,
                "path": row.get::<_, String>(1)?,
                "message": message,
                "severity": row.get::<_, String>(3)?,
                "is_test_path": row.get::<_, bool>(4)?,
            })))
        })
        .map_err(crate::query::db_err)?;
    rows.collect::<rusqlite::Result<Vec<Option<serde_json::Value>>>>()
        .map(|values| values.into_iter().flatten().collect())
        .map_err(crate::query::db_err)
}

fn is_expected_source_skip(message: &str) -> bool {
    matches!(
        message,
        "unsupported file type — skipped" | "minified/generated source — skipped"
    )
}

/// Production diagnostics and rule-loader failures block gates. Diagnostics
/// from test fixtures remain visible without making production analysis
/// incomplete.
fn blocks_gate(diagnostic: &serde_json::Value) -> bool {
    if let Some(blocking) = diagnostic
        .get("blocking")
        .and_then(serde_json::Value::as_bool)
    {
        return blocking;
    }
    diagnostic.get("source").and_then(|value| value.as_str()) != Some("persisted")
        || !diagnostic
            .get("is_test_path")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
            && diagnostic
                .get("message")
                .and_then(|value| value.as_str())
                .is_none_or(|message| !is_expected_source_skip(message))
}

/// Add a stable common shape while retaining legacy diagnostic fields.
///
/// Rule-loader, pattern, and SQL diagnostics historically exposed
/// `{rule_id,file,reason}` while persisted parser diagnostics exposed a
/// different shape. The additive fields let callers consume one tagged model
/// without breaking existing integrations that still read the old fields.
fn normalize_diagnostic(diagnostic: &mut serde_json::Value) {
    let persisted = diagnostic.get("source").and_then(|value| value.as_str()) == Some("persisted");
    let blocking = blocks_gate(diagnostic);
    let file = diagnostic
        .get("path")
        .or_else(|| diagnostic.get("file"))
        .and_then(|value| value.as_str())
        .unwrap_or("<unknown>")
        .to_owned();
    let message = diagnostic
        .get("message")
        .or_else(|| diagnostic.get("reason"))
        .and_then(|value| value.as_str())
        .unwrap_or("analysis diagnostic")
        .to_owned();
    let severity = diagnostic
        .get("severity")
        .and_then(|value| value.as_str())
        .unwrap_or(if blocking { "error" } else { "info" })
        .to_owned();
    diagnostic["kind"] = serde_json::json!(if persisted { "source" } else { "rules" });
    diagnostic["source"] = serde_json::json!(if persisted { "persisted" } else { "rules" });
    diagnostic["message"] = serde_json::json!(message);
    diagnostic["severity"] = serde_json::json!(severity);
    diagnostic["blocking"] = serde_json::json!(blocking);
    diagnostic["location"] = serde_json::json!({ "file": file });
}

fn filter_generated(
    mut findings: Vec<crate::rules::finding::Finding>,
) -> Vec<crate::rules::finding::Finding> {
    let before = findings.len();
    findings.retain(|finding| {
        !crate::query::noise_filter::is_generated_or_vendored_path(&finding.location.file)
    });
    let dropped = before - findings.len();
    if dropped > 0 {
        tracing::info!(dropped, "suppressed findings on generated/vendored files");
    }
    findings
}

fn rewrite_bearing_count(
    rules: &[crate::rules::Rule],
    findings: &[crate::rules::finding::Finding],
) -> usize {
    let rule_ids: std::collections::HashSet<&str> = rules
        .iter()
        .filter(|rule| rule.kind == crate::rules::RuleKind::Pattern && rule.rewrite.is_some())
        .map(|rule| rule.id.as_str())
        .collect();
    findings
        .iter()
        .filter(|finding| rule_ids.contains(finding.rule_id.as_str()))
        .count()
}

fn build_scan_payload(
    findings: Vec<crate::rules::finding::Finding>,
    diagnostics: Vec<serde_json::Value>,
    stale_suppressions: Vec<crate::rules::suppress::StaleSuppression>,
) -> serde_json::Value {
    let mut payload = serde_json::json!({
        "findings": collapse_clone_bands(findings),
        "diagnostics": diagnostics,
    });
    if !stale_suppressions.is_empty() {
        payload["stale_suppressions"] = serde_json::json!(stale_suppressions);
    }
    payload
}

fn attach_gate(payload: &mut serde_json::Value, threshold: Severity, selected: Option<&[String]>) {
    let diagnostic_count = payload["diagnostics"].as_array().map_or(0, Vec::len);
    let blocking_diagnostic_count = payload["diagnostics"].as_array().map_or(0, |diagnostics| {
        diagnostics
            .iter()
            .filter(|diagnostic| blocks_gate(diagnostic))
            .count()
    });
    let incomplete = blocking_diagnostic_count > 0;
    let blocking_findings = blocking_finding_count(payload, threshold, selected);
    let (status, outcome, outcome_reasons) = gate_decision(blocking_findings, incomplete);
    payload["analysis"] = serde_json::json!({
        "status": if incomplete { "incomplete" } else { "complete" },
    });
    payload["outcome"] = serde_json::json!(outcome);
    payload["outcome_reasons"] = serde_json::json!(outcome_reasons);
    payload["gate"] = serde_json::json!({
        "status": status,
        "severity_threshold": severity_name(threshold),
        "blocking_findings": blocking_findings,
        "diagnostic_count": diagnostic_count,
        "blocking_diagnostic_count": blocking_diagnostic_count,
    });
    if let Some(ids) = selected {
        payload["gate"]["severity_threshold"] = serde_json::Value::Null;
        payload["gate"]["rule_ids"] = serde_json::json!(ids);
    }
}

fn blocking_finding_count(
    payload: &serde_json::Value,
    threshold: Severity,
    selected: Option<&[String]>,
) -> usize {
    let Some(ids) = selected else {
        return unresolved_finding_count(payload, threshold);
    };
    payload["findings"].as_array().map_or(0, |findings| {
        findings
            .iter()
            .filter(|finding| finding["rewrite_status"].as_str() != Some("applied"))
            .filter(|finding| {
                finding["rule_id"]
                    .as_str()
                    .is_some_and(|id| ids.iter().any(|selected| selected == id))
            })
            .count()
    })
}

fn gate_decision(
    blocking_findings: usize,
    incomplete: bool,
) -> (&'static str, &'static str, &'static [&'static str]) {
    match (blocking_findings > 0, incomplete) {
        (true, true) => (
            "fail",
            "code-quality-error",
            &["code-quality-error", "analysis-incomplete"],
        ),
        (true, false) => ("fail", "code-quality-error", &["code-quality-error"]),
        (false, true) => ("unknown", "analysis-incomplete", &["analysis-incomplete"]),
        (false, false) => ("pass", "passed", &["passed"]),
    }
}

fn attach_policy(
    payload: &mut serde_json::Value,
    rules: &[crate::rules::Rule],
    origins: &HashMap<String, crate::rules::RuleOrigin>,
    threshold: Severity,
    selected: Option<&[String]>,
) {
    let explicit = selected.is_some();
    let gating_rule_count = match selected {
        Some(ids) => ids.len(),
        None => rules
            .iter()
            .filter(|rule| rule.severity >= threshold)
            .count(),
    };
    let mut source_counts = BTreeMap::from([
        ("builtin", 0usize),
        ("override", 0usize),
        ("custom", 0usize),
    ]);
    for rule in rules {
        let key = match origins.get(&rule.id) {
            Some(crate::rules::RuleOrigin::Builtin) => "builtin",
            Some(crate::rules::RuleOrigin::Override) => "override",
            Some(crate::rules::RuleOrigin::Custom) | None => "custom",
        };
        *source_counts.get_mut(key).expect("policy source key") += 1;
    }
    let fingerprint = policy_fingerprint(rules, origins, threshold, selected);
    let mut policy = serde_json::json!({
        "mode": if explicit { "selected-rules" } else { "severity-threshold" },
        "active_rule_count": rules.len(),
        "gating_rule_count": gating_rule_count,
        "severity_threshold": if explicit {
            serde_json::Value::Null
        } else {
            serde_json::json!(severity_name(threshold))
        },
        "sources": source_counts,
        "fingerprint": fingerprint,
    });
    if let Some(ids) = selected {
        policy["rule_ids"] = serde_json::json!(ids);
    }
    payload["policy"] = policy;
}

fn policy_fingerprint(
    rules: &[crate::rules::Rule],
    origins: &HashMap<String, crate::rules::RuleOrigin>,
    threshold: Severity,
    selected: Option<&[String]>,
) -> String {
    let mut definitions: Vec<serde_json::Value> = rules
        .iter()
        .map(|rule| {
            serde_json::json!({
                "id": rule.id,
                "origin": match origins.get(&rule.id) {
                    Some(crate::rules::RuleOrigin::Builtin) => "builtin",
                    Some(crate::rules::RuleOrigin::Override) => "override",
                    Some(crate::rules::RuleOrigin::Custom) | None => "custom",
                },
                "definition": serde_json::to_value(rule).expect("rule serializes"),
            })
        })
        .collect();
    definitions.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
    let policy = serde_json::json!({
        "threshold": severity_name(threshold),
        "selected": selected,
        "rules": definitions,
    });
    let mut serialized = String::new();
    write_canonical_json(&policy, &mut serialized);
    format!("fnv1a64:{:016x}", fnv1a64(serialized.as_bytes()))
}

/// Serialize JSON with object keys sorted at every nesting level.
/// Rule definitions contain maps, so relying on insertion order would make
/// otherwise identical policy fingerprints unstable across loader paths.
fn write_canonical_json(value: &serde_json::Value, output: &mut String) {
    match value {
        serde_json::Value::Object(map) => {
            output.push('{');
            let mut keys: Vec<&str> = map.keys().map(String::as_str).collect();
            keys.sort_unstable();
            for (index, key) in keys.into_iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                output.push_str(&serde_json::to_string(key).expect("JSON key serializes"));
                output.push(':');
                write_canonical_json(&map[key], output);
            }
            output.push('}');
        }
        serde_json::Value::Array(values) => {
            output.push('[');
            for (index, value) in values.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                write_canonical_json(value, output);
            }
            output.push(']');
        }
        scalar => output.push_str(&serde_json::to_string(scalar).expect("JSON value serializes")),
    }
}

fn fnv1a64(bytes: &[u8]) -> u64 {
    bytes.iter().fold(0xcbf29ce484222325, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(0x100000001b3)
    })
}

fn attach_findings_summary(payload: &mut serde_json::Value) {
    let findings = payload["findings"].as_array().expect("findings array");
    let mut by_rule = BTreeMap::<String, usize>::new();
    let mut by_severity = BTreeMap::from([
        ("error".to_owned(), 0usize),
        ("warning".to_owned(), 0usize),
        ("info".to_owned(), 0usize),
    ]);
    for finding in findings {
        if let Some(rule_id) = finding["rule_id"].as_str() {
            *by_rule.entry(rule_id.to_owned()).or_default() += 1;
        }
        if let Some(severity) = finding["severity"].as_str() {
            *by_severity.entry(severity.to_owned()).or_default() += 1;
        }
    }
    payload["findings_summary"] = serde_json::json!({
        "total": findings.len(),
        "shown": findings.len(),
        "truncated": false,
        "by_rule": by_rule,
        "by_severity": by_severity,
    });
}

fn truncate_findings(payload: &mut serde_json::Value, options: FindingsOptions) {
    let findings = payload["findings"].take();
    let Some(findings) = findings.as_array() else {
        return;
    };
    let total = findings.len();
    let start = options.offset.min(total);
    let end = if options.full {
        total
    } else {
        start.saturating_add(options.limit).min(total)
    };
    let shown = end.saturating_sub(start);
    let truncated = start > 0 || end < total;
    payload["findings"] = serde_json::Value::Array(findings[start..end].to_vec());
    payload["findings_summary"]["shown"] = serde_json::json!(shown);
    payload["findings_summary"]["truncated"] = serde_json::json!(truncated);
    payload["findings_summary"]["offset"] = serde_json::json!(start);
    if truncated {
        let guide = serde_json::json!({
            "shown": shown,
            "total": total,
            "offset": start,
            "limit": if options.full { serde_json::Value::Null } else { serde_json::json!(options.limit) },
            "next_offset": if end < total { serde_json::json!(end) } else { serde_json::Value::Null },
            "request": if end < total {
                "set findingsOffset to next_offset, or set fullFindings to true"
            } else {
                "set fullFindings to true for all findings"
            },
        });
        payload["guide"]["truncated"]["findings"] = guide;
    }
}

fn severity_name(severity: Severity) -> &'static str {
    match severity {
        Severity::Error => "error",
        Severity::Warning => "warning",
        Severity::Info => "info",
    }
}

fn attach_rewrite_statuses(
    payload: &mut serde_json::Value,
    statuses: &HashMap<String, RewriteStatus>,
    expected_count: usize,
) {
    debug_assert_eq!(statuses.len(), expected_count);
    let mut summary = serde_json::Map::new();
    for (status, count) in count_statuses(statuses) {
        summary.insert(status.to_string(), serde_json::json!(count));
    }
    for finding in payload["findings"].as_array_mut().expect("findings array") {
        if let Some(status) = finding["id"].as_str().and_then(|id| statuses.get(id)) {
            finding["rewrite_status"] = serde_json::json!(status);
        }
    }
    if !summary.is_empty() {
        payload["rewrite_summary"] = serde_json::Value::Object(summary);
    }
}

/// The built-in clone policy also supports legacy user overrides.
const CLONE_RULE_ID: &str = "duplicate-code-clone";

/// Collapse members after suppression, preserving verified group identity.
/// Legacy unverified bands still merge when their member sets match.
fn collapse_clone_bands(
    findings: Vec<crate::rules::finding::Finding>,
) -> Vec<crate::rules::finding::Finding> {
    use crate::rules::finding::Finding;
    use std::collections::BTreeMap;

    type CloneMember = (String, u32, u32);
    type CloneGroup = (Vec<String>, Vec<Finding>);

    let mut bands: BTreeMap<String, Vec<Finding>> = BTreeMap::new();
    let mut out = Vec::new();
    for finding in findings {
        match finding
            .evidence
            .get("label")
            .and_then(|v| v.as_str())
            .map(str::to_string)
        {
            Some(label) if finding.rule_id == CLONE_RULE_ID => {
                bands.entry(label).or_default().push(finding);
            }
            _ => out.push(finding),
        }
    }

    let mut member_sets: BTreeMap<Vec<CloneMember>, CloneGroup> = BTreeMap::new();
    for (label, mut members) in bands {
        members.sort_by_key(clone_member_key);
        if members[0].evidence["verification"] == "exact-clone" {
            out.push(collapsed_clone_finding(vec![label], &members));
            continue;
        }
        let key = members.iter().map(clone_member_key).collect();
        member_sets
            .entry(key)
            .and_modify(|(labels, _)| labels.push(label.clone()))
            .or_insert_with(|| (vec![label], members));
    }

    for (_, (mut labels, members)) in member_sets {
        labels.sort();
        out.push(collapsed_clone_finding(labels, &members));
    }
    out
}

fn clone_member_key(finding: &crate::rules::finding::Finding) -> (String, u32, u32) {
    (
        finding.location.file.clone(),
        finding.location.span.start_line,
        finding.location.span.end_line,
    )
}

fn collapsed_clone_finding(
    labels: Vec<String>,
    members: &[crate::rules::finding::Finding],
) -> crate::rules::finding::Finding {
    use crate::rules::finding::{Finding, finding_id};

    let label = &labels[0];
    let member_json: Vec<_> = members
        .iter()
        .map(|member| {
            serde_json::json!({
                "file": member.location.file,
                "startLine": member.location.span.start_line,
                "endLine": member.location.span.end_line,
            })
        })
        .collect();
    let anchor = &members[0];
    let mut evidence = anchor.evidence.clone();
    evidence["band"] = serde_json::json!(label);
    evidence["bands"] = serde_json::json!(labels);
    evidence["members"] = serde_json::json!(member_json);
    Finding {
        id: finding_id(&anchor.rule_id, label, &anchor.location.span),
        rule_id: anchor.rule_id.clone(),
        severity: anchor.severity,
        message: anchor.message.clone(),
        location: anchor.location.clone(),
        evidence,
        remediation: anchor.remediation.clone(),
        certainty: anchor.certainty,
        agent_instructions: anchor.agent_instructions.clone(),
        rewrite_status: None,
        matched_file_state: None,
    }
}

/// Hoist per-rule static text out of every finding into a one-per-rule
/// `rules` legend, so the scan payload states each rule's `message` +
/// `remediation` once instead of re-inlining them on every finding.
///
/// Audit F2: on a large C# repo the identical duplicate-code-clone
/// message+remediation (~180 B) repeated across ~6,555 findings ≈ 1.3 MB of
/// pure repetition. Lossless:
///   - `remediation` is static per rule (never interpolated — see
///     `sql::run_sql_rule`, which renders only `message`), so it is always
///     dropped from the finding and read from `rules[rule_id].remediation`.
///   - `message` MAY be interpolated per finding (SQL `{column}` templates,
///     e.g. `fat-interface` → "declares 16 methods"), so it is dropped only
///     when it still equals the rule's template; interpolated messages stay
///     inline on the finding.
///
/// The legend carries the template `message` for every rule that fired, so a
/// reader always has the human text for each `rule_id`.
fn hoist_rule_legend(payload: &mut serde_json::Value, rules: &[crate::rules::Rule]) {
    let Some(findings) = payload.get_mut("findings").and_then(|f| f.as_array_mut()) else {
        return;
    };
    if findings.is_empty() {
        return;
    }
    let by_id: std::collections::HashMap<&str, &crate::rules::Rule> =
        rules.iter().map(|r| (r.id.as_str(), r)).collect();
    let mut legend = serde_json::Map::new();
    for finding in findings.iter_mut() {
        let Some(obj) = finding.as_object_mut() else {
            continue;
        };
        let Some(rule_id) = obj
            .get("rule_id")
            .and_then(|v| v.as_str())
            .map(str::to_string)
        else {
            continue;
        };
        let Some(rule) = by_id.get(rule_id.as_str()) else {
            continue;
        };
        // remediation: always static -> legend only.
        obj.remove("remediation");
        // message: drop when it still equals the rule template (static);
        // keep when interpolation changed it.
        if obj.get("message").and_then(|v| v.as_str()) == Some(rule.message.as_str()) {
            obj.remove("message");
        }
        if !legend.contains_key(&rule_id) {
            let mut entry = serde_json::Map::new();
            entry.insert("message".into(), serde_json::json!(rule.message));
            if let Some(rem) = &rule.remediation {
                entry.insert("remediation".into(), serde_json::json!(rem));
            }
            legend.insert(rule_id, serde_json::Value::Object(entry));
        }
    }
    payload["rules"] = serde_json::Value::Object(legend);
}

/// Count findings per `RewriteStatus` value, emitting kebab-case status
/// names (e.g. `"skipped-dirty"`) — the same names the per-finding field
/// serializes to. Iteration order is deterministic by construction of the
/// status enum's `Serialize` mapping (declaration order).
fn count_statuses(statuses: &HashMap<String, RewriteStatus>) -> Vec<(&'static str, usize)> {
    use crate::rules::rewrite::RewriteStatus::*;
    let mut counts: Vec<(&str, usize)> = vec![
        ("applied", 0),
        ("skipped-dirty", 0),
        ("skipped-overlap", 0),
        ("skipped-conflict", 0),
    ];
    for status in statuses.values() {
        let key = match status {
            Applied => 0usize,
            SkippedDirty => 1,
            SkippedOverlap => 2,
            SkippedConflict => 3,
        };
        counts[key].1 += 1;
    }
    counts.into_iter().filter(|(_, n)| *n > 0).collect()
}

struct FileTarget<'a> {
    finding: &'a crate::rules::finding::Finding,
    template: &'a str,
    target: RewriteTarget,
}

/// Apply every `rewrite`-bearing finding's substitution to disk, gated per
/// file by git status, and return each finding's outcome.
///
/// Returns a map from finding id to its `RewriteStatus` — only findings
/// whose rule carries a `rewrite` template are present. Callers (the JSON
/// envelope / summary in `apply-output-envelope-and-exit-code`) attach the
/// status to the finding and count statuses from this map.
///
/// Per file, in order: git-clean check (dirty → every finding in the file
/// is `skipped-dirty`, unless `force`; one batched git probe serves the
/// whole run — CODE-003), then span planning (`plan_file_rewrites`: sort,
/// skip overlaps), then a single atomic write splicing every applied
/// replacement into the file content.
///
/// Findings are grouped by the **physical** file that will be written — the
/// canonical target, so a symlinked entry and its real target (both walked,
/// both matching) plan as one file and produce a single write
/// (CORRECTNESS-004): the link survives and the real file is rewritten.
pub(crate) fn apply_rewrites(
    rules: &[crate::rules::Rule],
    findings: &[crate::rules::finding::Finding],
    repo_root: &Path,
    force: bool,
) -> Result<HashMap<String, RewriteStatus>, ApiError> {
    let rewrite_by_rule: HashMap<&str, &str> = rules
        .iter()
        .filter(|r| r.kind == crate::rules::RuleKind::Pattern)
        .filter_map(|r| {
            r.rewrite
                .as_deref()
                .map(|template| (r.id.as_str(), template))
        })
        .collect();
    if rewrite_by_rule.is_empty() {
        return Ok(HashMap::new());
    }

    let by_file = group_rewrite_targets(findings, &rewrite_by_rule);

    // One git probe for the whole run (CODE-003). A canonicalized
    // repo_root keeps `--is-inside-work-tree` correct for relative inputs
    // (CORRECTNESS-002). `force` skips the gate entirely, as before.
    let repo_root_abs = repo_root.canonicalize().unwrap_or_else(|_| {
        std::path::absolute(repo_root).unwrap_or_else(|_| repo_root.to_path_buf())
    });
    let real_paths: Vec<std::path::PathBuf> = by_file.keys().cloned().collect();
    let gate = if force {
        GitGate::NotAGitRepo
    } else {
        git_gate(&repo_root_abs, &real_paths)
    };
    if matches!(gate, GitGate::Unverifiable) {
        tracing::warn!(
            "apply: git status failed; every file treated as dirty and skipped (use --force to override)"
        );
    }

    let mut statuses = HashMap::new();
    for (real_path, targets) in &by_file {
        apply_file_rewrites(real_path, targets, &gate, &mut statuses);
    }
    Ok(statuses)
}

fn group_rewrite_targets<'a>(
    findings: &'a [crate::rules::finding::Finding],
    rewrite_by_rule: &HashMap<&str, &'a str>,
) -> HashMap<std::path::PathBuf, Vec<FileTarget<'a>>> {
    let mut by_file = HashMap::new();
    for finding in findings {
        let Some(template) = rewrite_by_rule.get(finding.rule_id.as_str()) else {
            continue;
        };
        let span = &finding.location.span;
        let real = crate::rules::finding::resolve_real_path(&finding.location.file);
        by_file
            .entry(real)
            .or_insert_with(Vec::new)
            .push(FileTarget {
                finding,
                template,
                target: RewriteTarget {
                    start_byte: span.start_byte,
                    end_byte: span.end_byte,
                    replacement: String::new(),
                },
            });
    }
    by_file
}

fn apply_file_rewrites(
    real_path: &Path,
    targets: &[FileTarget<'_>],
    gate: &GitGate,
    statuses: &mut HashMap<String, RewriteStatus>,
) {
    if gate.dirty(real_path) {
        mark_targets(targets, RewriteStatus::SkippedDirty, statuses);
        return;
    }
    let applied = plan_rewrite_targets(targets, statuses);
    if applied.is_empty() {
        return;
    }
    let Some(content) = read_verified_content(real_path, targets, statuses) else {
        return;
    };
    let Some(rewritten) = render_rewrites(&content, &applied) else {
        mark_targets(targets, RewriteStatus::SkippedConflict, statuses);
        tracing::warn!(file = %real_path.display(), "apply: span not on a UTF-8 boundary; file skipped");
        return;
    };
    if gate.recheck_dirty(real_path) {
        mark_targets(targets, RewriteStatus::SkippedDirty, statuses);
        tracing::warn!(file = %real_path.display(), "apply: file became dirty since the initial git check; skipped");
        return;
    }
    if let Err(error) = write_atomic(real_path, &rewritten) {
        mark_targets(targets, RewriteStatus::SkippedConflict, statuses);
        tracing::warn!(file = %real_path.display(), "apply: write failed, file skipped: {error}");
    }
}

fn mark_targets(
    targets: &[FileTarget<'_>],
    status: RewriteStatus,
    statuses: &mut HashMap<String, RewriteStatus>,
) {
    for target in targets {
        statuses.insert(target.finding.id.clone(), status);
    }
}

fn plan_rewrite_targets<'a>(
    targets: &'a [FileTarget<'a>],
    statuses: &mut HashMap<String, RewriteStatus>,
) -> Vec<&'a FileTarget<'a>> {
    let rewrites: Vec<_> = targets.iter().map(|target| target.target.clone()).collect();
    let plans = crate::rules::rewrite::plan_file_rewrites(&rewrites);
    targets
        .iter()
        .zip(plans)
        .filter_map(|(target, plan)| {
            let status = match plan {
                crate::rules::rewrite::RewritePlan::Apply => RewriteStatus::Applied,
                crate::rules::rewrite::RewritePlan::SkippedOverlap => RewriteStatus::SkippedOverlap,
            };
            statuses.insert(target.finding.id.clone(), status);
            matches!(status, RewriteStatus::Applied).then_some(target)
        })
        .collect()
}

fn read_verified_content(
    real_path: &Path,
    targets: &[FileTarget<'_>],
    statuses: &mut HashMap<String, RewriteStatus>,
) -> Option<String> {
    let state_before_read = crate::rules::finding::FileState::of(real_path);
    let content = match std::fs::read_to_string(real_path) {
        Ok(content) => content,
        Err(error) => {
            mark_targets(targets, RewriteStatus::SkippedConflict, statuses);
            tracing::warn!(file = %real_path.display(), "apply: unreadable file skipped: {error}");
            return None;
        }
    };
    let state_after_read = crate::rules::finding::FileState::of(real_path);
    let changed = targets
        .iter()
        .filter_map(|target| target.finding.matched_file_state)
        .any(|expected| {
            state_before_read != Some(expected)
                || state_after_read != Some(expected)
                || content.len() as u64 != expected.len
        });
    if changed {
        mark_targets(targets, RewriteStatus::SkippedConflict, statuses);
        tracing::warn!(
            file = %real_path.display(),
            "apply: file changed since it was matched; skipped to avoid misapplying stale offsets"
        );
        return None;
    }
    Some(content)
}

fn render_rewrites(content: &str, targets: &[&FileTarget<'_>]) -> Option<String> {
    let mut replacements: Vec<_> = targets
        .iter()
        .map(|target| RewriteTarget {
            start_byte: target.target.start_byte,
            end_byte: target.target.end_byte,
            replacement: crate::rules::rewrite::substitute_with_source(
                target.template,
                &target.finding.evidence,
                Some(content),
            ),
        })
        .collect();
    replacements.sort_by_key(|target| (target.start_byte, target.end_byte));
    splice(content, &replacements.iter().collect::<Vec<_>>())
}

/// Outcome of the batched git gate for one `--apply` run.
///
/// One git probe + one status call serve the whole run (CODE-003) instead
/// of a subprocess per rewritten file.
enum GitGate {
    /// git absent, or `repo_root` not inside a work tree → every file clean
    /// (no git state to be undone against — documented scope, CORRECTNESS-005).
    NotAGitRepo,
    /// A work tree exists but the status query failed (corrupt index,
    /// unreadable `.git`, unexpected output shape) → every file dirty.
    /// Failure-closed: an ungated write is worse than a skipped one
    /// (CORRECTNESS-005).
    Unverifiable,
    /// A work tree exists and status ran: its root (for a later per-file
    /// recheck) plus the set of dirty absolute paths.
    WorkTree(
        std::path::PathBuf,
        std::collections::HashSet<std::path::PathBuf>,
    ),
}

impl GitGate {
    /// Whether `real_path` (a canonical, absolute physical file path) is
    /// dirty under this gate.
    fn dirty(&self, real_path: &std::path::Path) -> bool {
        match self {
            GitGate::NotAGitRepo => false,
            GitGate::Unverifiable => true,
            GitGate::WorkTree(_, set) => set.contains(real_path),
        }
    }

    /// Re-probe git for exactly one file, right before it is written.
    ///
    /// The batched `dirty()` check runs once at the top of `apply_rewrites`
    /// (CODE-003); a file that becomes dirty *after* that probe but before
    /// its own write is otherwise overwritten regardless (an editor save, a
    /// concurrent process, `git checkout` racing the apply run). This is a
    /// second, single-file `git status` call scoped to files that are
    /// actually about to be written — one subprocess per output, not per
    /// input, so it doesn't reintroduce the per-candidate-file cost CODE-003
    /// removed.
    ///
    /// A status failure here fails closed (treated as dirty): skipping a
    /// write is always safer than risking one against a file we can no
    /// longer verify. `NotAGitRepo` has nothing to re-check against, so it
    /// stays clean, matching `dirty()`'s rationale.
    fn recheck_dirty(&self, real_path: &std::path::Path) -> bool {
        match self {
            GitGate::NotAGitRepo => false,
            GitGate::Unverifiable => true,
            GitGate::WorkTree(worktree, _) => {
                if !real_path.starts_with(worktree) {
                    return false;
                }
                match status_dirty_paths(worktree, &[real_path]) {
                    Some(dirty) => dirty.contains(real_path),
                    None => true,
                }
            }
        }
    }
}

/// Probe git once per apply run and classify the rewrite targets.
///
/// `repo_root` and `targets` are canonicalized here (resolving `..` and
/// symlink aliases such as macOS's `/var` → `/private/var`), so callers may
/// pass the paths they were given (CORRECTNESS-002); `targets` are the
/// physical files to be written, symlinks already resolved
/// (CORRECTNESS-004), and dirty matches are keyed by the same canonical
/// form (porcelain paths are canonicalized identically).
///
/// Sequence: `rev-parse --is-inside-work-tree` distinguishes "not a repo / no
/// git" (clean, documented) from "a work tree exists"; with a work tree
/// confirmed, a single batched `git status --porcelain=v1 -z -uall
/// --ignored` over the in-work-tree targets decides dirtiness. `--ignored`
/// closes CORRECTNESS-003 (an ignored untracked file is still untracked →
/// dirty). Any status failure after the work-tree probe is a genuine git
/// error → `Unverifiable` (failure-closed, CORRECTNESS-005). Targets whose
/// canonical path lies outside the work tree (symlink targets elsewhere)
/// cannot be gated — clean, same rationale as not-a-repo.
fn git_gate(repo_root: &std::path::Path, targets: &[std::path::PathBuf]) -> GitGate {
    let repo_root = repo_root.canonicalize().unwrap_or_else(|_| {
        std::path::absolute(repo_root).unwrap_or_else(|_| repo_root.to_path_buf())
    });
    let targets: Vec<std::path::PathBuf> = targets
        .iter()
        .map(|t| t.canonicalize().unwrap_or_else(|_| t.clone()))
        .collect();
    let Some(inside) = crate::git::run_git(&["rev-parse", "--is-inside-work-tree"], &repo_root)
    else {
        return GitGate::NotAGitRepo;
    };
    if inside.trim() != "true" {
        return GitGate::NotAGitRepo;
    }
    // Work tree confirmed. Resolve its root: porcelain paths are printed
    // relative to the work tree, so matching against absolute targets needs
    // it (repo_root may be a subdir of the work tree).
    let Some(top) = crate::git::run_git(&["rev-parse", "--show-toplevel"], &repo_root) else {
        return GitGate::Unverifiable;
    };
    let worktree = std::path::PathBuf::from(top.trim());

    let inside_targets: Vec<&std::path::Path> = targets
        .iter()
        .filter(|p| p.starts_with(&worktree))
        .map(|p| p.as_path())
        .collect();
    if inside_targets.is_empty() {
        return GitGate::WorkTree(worktree, std::collections::HashSet::new());
    }
    match status_dirty_paths(&worktree, &inside_targets) {
        Some(dirty) => GitGate::WorkTree(worktree, dirty),
        None => GitGate::Unverifiable,
    }
}

/// Run the batched status query (chunked so the command line stays well
/// under ARG_MAX for repo-wide codemods) and collect dirty absolute paths.
///
/// `None` when any status call fails or emits an unexpected record shape —
/// the caller then fails closed (every file dirty).
fn status_dirty_paths(
    worktree: &std::path::Path,
    targets: &[&std::path::Path],
) -> Option<std::collections::HashSet<std::path::PathBuf>> {
    // Conservative chunk size: ~1000 absolute paths stays far below the
    // macOS/Linux exec arg ceiling while keeping this O(chunks), not
    // O(files), subprocesses.
    const CHUNK: usize = 1000;
    let mut dirty = std::collections::HashSet::new();
    for chunk in targets.chunks(CHUNK) {
        let paths: Vec<String> = chunk
            .iter()
            .map(|p| p.to_string_lossy().into_owned())
            .collect();
        let mut args: Vec<&str> = vec![
            "-c",
            "status.renames=false",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored",
            "-z",
            "--",
        ];
        args.extend(paths.iter().map(|s| s.as_str()));
        let status = crate::git::run_git(&args, worktree)?;
        let paths = parse_porcelain_dirty_paths(&status)?;
        for p in paths {
            let joined = worktree.join(p);
            // Canonicalize so a dirty symlink entry matches its canonical
            // (write) target; deleted entries (canonicalize fails) never
            // match an existing target anyway.
            let canonical = std::fs::canonicalize(&joined).unwrap_or(joined);
            dirty.insert(canonical);
        }
    }
    Some(dirty)
}

/// Parse `git status --porcelain=v1 -z` output (run with
/// `status.renames=false`, so every record is the single-field `XY path`
/// shape — never the two-record rename form) into dirty paths, relative to
/// the work-tree root the call ran in.
///
/// A `!` status letter (an ignored entry, listed because of `--ignored`) is
/// dirty like any other change: an untracked file is dirty regardless of
/// ignore status (CORRECTNESS-003). A record that fails the `XY path` shape
/// is a wire-format surprise → `None` (caller fails closed).
fn parse_porcelain_dirty_paths(status: &str) -> Option<Vec<&str>> {
    let is_status_letter = |b: u8| {
        matches!(
            b,
            b' ' | b'M' | b'T' | b'A' | b'D' | b'R' | b'C' | b'U' | b'?' | b'!'
        )
    };
    let mut paths = Vec::new();
    for entry in status.split('\0') {
        if entry.is_empty() {
            continue;
        }
        let bytes = entry.as_bytes();
        if bytes.len() < 4
            || !is_status_letter(bytes[0])
            || !is_status_letter(bytes[1])
            || bytes[2] != b' '
        {
            return None;
        }
        paths.push(&entry[3..]);
    }
    Some(paths)
}

/// Splice `replacement` over every applied span of `content`, preserving all
/// other bytes exactly. `applied` must be sorted by span and non-overlapping
/// (as produced by `plan_file_rewrites` + sort). Returns `None` when a span
/// is not on a UTF-8 char boundary (tree-sitter spans are node boundaries,
/// so this is defensive).
fn splice(content: &str, applied: &[&RewriteTarget]) -> Option<String> {
    let mut out = String::with_capacity(content.len());
    let mut cursor = 0usize;
    for t in applied {
        let start = t.start_byte as usize;
        let end = t.end_byte as usize;
        if start < cursor
            || end > content.len()
            || !content.is_char_boundary(start)
            || !content.is_char_boundary(end)
        {
            return None;
        }
        out.push_str(&content[cursor..start]);
        out.push_str(&t.replacement);
        cursor = end;
    }
    out.push_str(&content[cursor..]);
    Some(out)
}

/// Write `content` to `path` atomically: write a temp file in the same
/// directory, then rename over the original — no partial writes on crash
/// mid-`--apply`. The temp file is removed if the rename fails.
///
/// The original file's permission bits are copied onto the temp file before
/// the rename (CORRECTNESS-001): an executable script stays executable and
/// a read-only file stays read-only after the rewrite — the swap never
/// silently resets the mode to the umask default. When the original does
/// not exist (a brand-new write) the temp keeps its default mode.
fn write_atomic(path: &Path, content: &str) -> std::io::Result<()> {
    let dir = path.parent().unwrap_or_else(|| Path::new("."));
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "out".to_string());
    let tmp = dir.join(format!(".{name}.varde-apply-tmp-{}", std::process::id()));
    if let Err(e) = std::fs::write(&tmp, content) {
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }
    // Preserve the original's mode on the temp before the swap; a missing
    // original (new file) falls back gracefully to the default mode.
    if let Ok(metadata) = std::fs::metadata(path)
        && let Err(e) = std::fs::set_permissions(&tmp, metadata.permissions())
    {
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }
    match std::fs::rename(&tmp, path) {
        Ok(()) => Ok(()),
        Err(e) => {
            let _ = std::fs::remove_file(&tmp);
            Err(e)
        }
    }
}

/// List the rules that would run for `{ repoRoot }` — the same merged,
/// built-in-aware set `scan_repo` loads — without executing a scan or
/// requiring a persisted DB.
///
/// Each entry is tagged `source`:
/// - `"builtin"`: a shipped default, unmodified by user/repo scope;
/// - `"override"`: a user/repo rule reusing a built-in id (the built-in is
///   shadowed, per `load_rules`'s override semantics);
/// - `"custom"`: a user/repo-only rule with no built-in counterpart.
///
/// Entries include the active serialized definition, excluding self-tests.
pub fn rules_list(input: &serde_json::Value) -> Result<serde_json::Value, ApiError> {
    let repo_path = require_repo_dir(input)?;

    let (rules, diagnostics, origins) = crate::rules::load_rules_with_origins(repo_path);

    let rules_json: Vec<serde_json::Value> = rules
        .iter()
        .map(|rule| {
            let source = match origins.get(&rule.id) {
                Some(crate::rules::RuleOrigin::Builtin) => "builtin",
                Some(crate::rules::RuleOrigin::Override) => "override",
                Some(crate::rules::RuleOrigin::Custom) => "custom",
                None => unreachable!("every active rule has an origin"),
            };
            let mut definition = serde_json::to_value(rule).expect("rule serializes");
            if rule.verification == Some(crate::rules::Verification::DependencyBoundary) {
                definition["configuration_status"] = serde_json::json!(
                    if crate::rules::boundary_configured(rule).unwrap_or(false) {
                        "configured"
                    } else {
                        "requires_configuration"
                    }
                );
            }

            definition["source"] = serde_json::json!(source);
            // Preserve the original listing's nullable display fields.
            definition["name"] = serde_json::json!(rule.name);
            definition["description"] = serde_json::json!(rule.description);
            definition
        })
        .collect();

    Ok(serde_json::json!({ "rules": rules_json, "diagnostics": diagnostics }))
}

/// Materialize the built-in rule packs as editable TOML files in the repo
/// or user rules dir (`{ repoRoot }`, plus `user`/`force` from the caller).
pub fn rules_seed(
    input: &serde_json::Value,
    user: bool,
    force: bool,
) -> Result<serde_json::Value, ApiError> {
    let repo_path = require_repo_dir(input)?;

    let target_dir = if user {
        crate::rules::user_rules_dir()
    } else {
        repo_path.join(".varde-code").join("rules")
    };

    let results = crate::rules::seed_builtin_rules(&target_dir, force).map_err(|e| {
        ApiError::new(
            "io_error",
            format!("failed to seed rules into {}: {e}", target_dir.display()),
        )
    })?;

    let seeded_json: Vec<serde_json::Value> = results
        .iter()
        .map(|r| {
            serde_json::json!({
                "fileName": r.file_name,
                "path": r.path.display().to_string(),
                "written": r.written,
                "skippedExisting": r.skipped_existing,
            })
        })
        .collect();

    Ok(serde_json::json!({ "targetDir": target_dir.display().to_string(), "seeded": seeded_json }))
}

/// Delete previously seeded built-in rule pack files from the repo or user
/// rules dir (`{ repoRoot }`, plus `user`/`force` from the caller).
///
/// Only removes files matching a shipped built-in pack's name; custom rule
/// files in the same directory are left alone. A seeded file that was
/// customized since seeding is skipped unless `force` is true.
pub fn rules_remove(
    input: &serde_json::Value,
    user: bool,
    force: bool,
) -> Result<serde_json::Value, ApiError> {
    let repo_path = require_repo_dir(input)?;

    let target_dir = if user {
        crate::rules::user_rules_dir()
    } else {
        repo_path.join(".varde-code").join("rules")
    };

    let results = crate::rules::unseed_builtin_rules(&target_dir, force).map_err(|e| {
        ApiError::new(
            "io_error",
            format!(
                "failed to remove seeded rules from {}: {e}",
                target_dir.display()
            ),
        )
    })?;

    let removed_json: Vec<serde_json::Value> = results
        .iter()
        .map(|r| {
            serde_json::json!({
                "fileName": r.file_name,
                "path": r.path.display().to_string(),
                "removed": r.removed,
                "skippedModified": r.skipped_modified,
            })
        })
        .collect();

    Ok(
        serde_json::json!({ "targetDir": target_dir.display().to_string(), "removed": removed_json }),
    )
}

#[cfg(test)]
mod threshold {
    use super::*;
    use crate::rules::Severity;

    #[test]
    fn selected_policy_counts_only_unresolved_selected_findings() {
        let mut payload = serde_json::json!({
            "diagnostics": [],
            "findings": [
                {"rule_id": "chosen", "severity": "info", "rewrite_status": "applied"},
                {"rule_id": "chosen", "severity": "info", "rewrite_status": "skipped_dirty"},
                {"rule_id": "other", "severity": "error"}
            ]
        });
        attach_gate(&mut payload, Severity::Error, Some(&["chosen".into()]));
        assert_eq!(payload["gate"]["blocking_findings"], 1);
        assert_eq!(payload["gate"]["status"], "fail");
        payload["findings"].as_array_mut().unwrap().remove(1);
        attach_gate(&mut payload, Severity::Error, Some(&["chosen".into()]));
        assert_eq!(payload["gate"]["status"], "pass");
    }

    #[test]
    fn persisted_test_diagnostics_do_not_block_the_gate() {
        let fixture = serde_json::json!({
            "source": "persisted",
            "message": "syntax error — partial extract kept",
            "is_test_path": true
        });
        let production = serde_json::json!({
            "source": "persisted",
            "message": "syntax error — partial extract kept",
            "is_test_path": false
        });
        assert!(!blocks_gate(&fixture));
        assert!(blocks_gate(&production));
    }

    #[test]
    fn diagnostic_counts_distinguish_visible_and_blocking_entries() {
        let mut payload = serde_json::json!({
            "diagnostics": [
                {
                    "source": "persisted",
                    "message": "syntax error — partial extract kept",
                    "is_test_path": true
                },
                {
                    "source": "rules",
                    "message": "invalid rule"
                }
            ],
            "findings": []
        });
        attach_gate(&mut payload, Severity::Error, None);
        assert_eq!(payload["gate"]["diagnostic_count"], 2);
        assert_eq!(payload["gate"]["blocking_diagnostic_count"], 1);
        assert_eq!(payload["analysis"]["status"], "incomplete");
        assert_eq!(payload["gate"]["status"], "unknown");
    }

    fn payload_with_severities(severities: &[&str]) -> serde_json::Value {
        let findings: Vec<serde_json::Value> = severities
            .iter()
            .map(|s| serde_json::json!({ "severity": s, "id": "x", "rule_id": "r", "message": "m", "location": {} }))
            .collect();
        serde_json::json!({ "findings": findings, "diagnostics": [] })
    }

    #[test]
    fn default_threshold_is_error() {
        let input = serde_json::json!({ "repoRoot": "/tmp/x" });
        assert_eq!(
            severity_threshold(&input).expect("defaults"),
            Severity::Error
        );
        let input = serde_json::json!({ "repoRoot": "/tmp/x", "severityThreshold": "warning" });
        assert_eq!(
            severity_threshold(&input).expect("parses"),
            Severity::Warning
        );
        let input = serde_json::json!({ "repoRoot": "/tmp/x", "severityThreshold": "bogus" });
        assert!(
            severity_threshold(&input).is_err(),
            "unknown level rejected"
        );
    }

    #[test]
    fn findings_at_or_above_compares_against_threshold() {
        // Default threshold error: error trips it, warning/info do not.
        assert!(findings_at_or_above(
            &payload_with_severities(&["error"]),
            Severity::Error
        ));
        assert!(!findings_at_or_above(
            &payload_with_severities(&["warning"]),
            Severity::Error
        ));
        assert!(!findings_at_or_above(
            &payload_with_severities(&["info"]),
            Severity::Error
        ));
        assert!(!findings_at_or_above(
            &payload_with_severities(&[]),
            Severity::Error
        ));
        // Lower threshold: warning trips it.
        assert!(findings_at_or_above(
            &payload_with_severities(&["warning"]),
            Severity::Warning
        ));
        assert!(findings_at_or_above(
            &payload_with_severities(&["info"]),
            Severity::Info
        ));
        assert!(!findings_at_or_above(
            &payload_with_severities(&["info"]),
            Severity::Warning
        ));
        // Missing severity never trips a threshold.
        let no_severity = serde_json::json!({ "findings": [{ "id": "x" }], "diagnostics": [] });
        assert!(!findings_at_or_above(&no_severity, Severity::Info));
    }

    fn payload_with_rewrite_statuses(items: &[(&str, Option<&str>)]) -> serde_json::Value {
        let findings: Vec<serde_json::Value> = items
            .iter()
            .map(|(severity, status)| {
                let mut f = serde_json::json!({ "severity": severity, "id": "x", "rule_id": "r", "message": "m", "location": {} });
                if let Some(status) = status {
                    f["rewrite_status"] = serde_json::json!(status);
                }
                f
            })
            .collect();
        serde_json::json!({ "findings": findings, "diagnostics": [] })
    }

    #[test]
    fn unresolved_gate_ignores_applied_findings_but_not_skipped() {
        let err = Severity::Error;
        // Applied error finding → resolved, gate passes.
        assert!(!unresolved_findings_at_or_above(
            &payload_with_rewrite_statuses(&[("error", Some("applied"))]),
            err
        ));
        // Skipped error finding → unresolved, gate fails.
        for status in [
            Some("skipped-dirty"),
            Some("skipped-overlap"),
            Some("skipped-conflict"),
        ] {
            assert!(
                unresolved_findings_at_or_above(
                    &payload_with_rewrite_statuses(&[("error", status)]),
                    err
                ),
                "{status:?} must remain unresolved"
            );
        }
        // No rewrite_status at all (SQL finding, non-apply run) → gates as before.
        assert!(unresolved_findings_at_or_above(
            &payload_with_rewrite_statuses(&[("error", None)]),
            err
        ));
        assert!(
            !unresolved_findings_at_or_above(
                &payload_with_rewrite_statuses(&[("warning", Some("applied"))]),
                err
            ),
            "applied warning below threshold never trips"
        );
        // Mixed: one applied error + one skipped error → still unresolved.
        assert!(unresolved_findings_at_or_above(
            &payload_with_rewrite_statuses(&[
                ("error", Some("applied")),
                ("error", Some("skipped-dirty"))
            ]),
            err
        ));
    }

    #[test]
    fn unresolved_gate_matches_findings_at_or_above_when_no_statuses() {
        // Non-apply runs have no rewrite_status → both gates agree.
        for sevs in [&["error"][..], &["warning"][..], &[][..]] {
            let payload = payload_with_severities(sevs);
            assert_eq!(
                findings_at_or_above(&payload, Severity::Error),
                unresolved_findings_at_or_above(&payload, Severity::Error)
            );
        }
    }
}

#[cfg(test)]
mod orchestration {
    use super::*;

    const TS_FIXTURE: &str = r#"
async function fetchData(): Promise<void> {
  console.trace("async log");
}
"#;

    const RULE_PACK: &str = r#"
[[rule]]
id = "no-console"
kind = "pattern"
severity = "warning"
message = "console call detected"
pattern = "console.trace($MSG)"

[[rule]]
id = "function-count"
kind = "sql"
severity = "error"
message = "function present"
query = "SELECT f.path AS file, e.start_line AS line FROM entities e JOIN files f ON f.id = e.file_id WHERE e.kind = 0"
"#;

    fn tempdir(tag: &str) -> std::path::PathBuf {
        let dir =
            std::env::temp_dir().join(format!("varde-scan-flow-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        dir
    }

    fn write(path: &std::path::Path, contents: &str) {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).expect("parent dir creates");
        }
        std::fs::write(path, contents).expect("fixture writes");
    }

    /// Build a fresh index using `home` as the conventional DB root.
    fn with_fresh_db(
        home: &std::path::Path,
        repo: &std::path::Path,
    ) -> crate::test_support::HomeOverride {
        let home_override = crate::test_support::HomeOverride::while_locked(home);
        crate::build::run_with_force(repo.to_str().expect("repo is utf8"), true)
            .expect("fresh build succeeds");
        home_override
    }

    /// Run `git <args>` inside `repo`, asserting success.
    fn git(repo: &std::path::Path, args: &[&str]) {
        let status = std::process::Command::new("git")
            .args(args)
            .current_dir(repo)
            .status()
            .expect("git runs");
        assert!(status.success(), "git {args:?} failed");
    }

    /// Init a git repo at `repo` and commit every current file.
    fn git_init_and_commit(repo: &std::path::Path) {
        git(repo, &["init", "-q"]);
        git(repo, &["config", "user.email", "test@example.com"]);
        git(repo, &["config", "user.name", "test"]);
        git(repo, &["add", "-A"]);
        git(repo, &["commit", "-q", "-m", "initial"]);
    }

    /// Rule pack with a pattern rule carrying a `rewrite` template
    /// (`console.trace($MSG)` → `console.info($MSG)`).
    const REWRITE_RULE_PACK: &str = r#"
[[rule]]
id = "no-console"
kind = "pattern"
severity = "warning"
message = "console call detected"
pattern = "console.trace($MSG)"
rewrite = "console.info($MSG)"
"#;

    const TS_WITH_TRACE: &str = r#"
async function fetchData(): Promise<void> {
  console.trace("async log");
}
"#;

    const VARIADIC_REWRITE_RULE_PACK: &str = r#"
[[rule]]
id = "rename-function"
kind = "pattern"
severity = "warning"
message = "rename function"
pattern = "function $NAME() { $$$BODY }"
rewrite = "function after() { $$$BODY }"
languages = ["typescript"]

[[rule]]
id = "rename-call"
kind = "pattern"
severity = "warning"
message = "rename call"
pattern = "before($$$ARGS)"
rewrite = "after($$$ARGS)"
languages = ["typescript"]
"#;

    const TS_WITH_VARIADIC_CAPTURES: &str =
        "function beforeBody() { first();\n  second(); }\nbefore(alpha ,\n  beta);\n";

    /// Error-severity rewrite rule — for the exit-code gate test: an applied
    /// error finding is resolved, a skipped one is not.
    const REWRITE_RULE_PACK_ERROR: &str = r#"
[[rule]]
id = "no-console-error"
kind = "pattern"
severity = "error"
message = "console call detected"
pattern = "console.trace($MSG)"
rewrite = "console.info($MSG)"
"#;

    fn setup_apply_repo(
        tag: &str,
        home: &std::path::Path,
        fixture: &str,
    ) -> (std::path::PathBuf, crate::test_support::HomeOverride) {
        let repo = tempdir(tag);
        write(&repo.join("main.ts"), fixture);
        write(&repo.join(".varde-code/rules/pack.toml"), REWRITE_RULE_PACK);
        let home_override = with_fresh_db(home, &repo);
        (repo, home_override)
    }

    #[test]
    fn scan_without_apply_writes_nothing() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-noapply");
        let (repo, _home_override) = setup_apply_repo("repo-noapply", &home, TS_WITH_TRACE);
        git_init_and_commit(&repo);
        let before = std::fs::read_to_string(repo.join("main.ts")).expect("fixture reads");

        let input = serde_json::json!({ "repoRoot": repo.display().to_string() });
        let payload = scan_repo(&input).expect("read-only scan succeeds");
        assert!(!payload["findings"].as_array().expect("array").is_empty());
        // No apply flag → no write; the file is byte-identical.
        assert_eq!(
            std::fs::read_to_string(repo.join("main.ts")).expect("reads"),
            before
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn scan_with_apply_rewrites_clean_git_file_atomically() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-apply-clean");
        let (repo, _home_override) = setup_apply_repo("repo-apply-clean", &home, TS_WITH_TRACE);
        git_init_and_commit(&repo);

        let input = serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        });
        let payload = scan_repo(&input).expect("apply scan succeeds");
        let findings = payload["findings"].as_array().expect("findings array");
        assert_eq!(findings.len(), 1, "one trace finding: {findings:?}");
        // Envelope: the rewrite-bearing finding carries rewrite_status=applied.
        assert_eq!(
            findings[0]["rewrite_status"], "applied",
            "per-finding rewrite_status: {findings:?}"
        );
        // Top-level summary counts it.
        assert_eq!(
            payload["rewrite_summary"],
            serde_json::json!({ "applied": 1 })
        );

        let rewritten = std::fs::read_to_string(repo.join("main.ts")).expect("reads");
        assert!(
            rewritten.contains("console.info(\"async log\")"),
            "matched span replaced: {rewritten}"
        );
        assert!(
            !rewritten.contains("console.trace"),
            "no trace remains: {rewritten}"
        );
        // Byte-exact elsewhere: the enclosing function text is untouched.
        assert!(rewritten.contains("async function fetchData(): Promise<void> {"));
        // No temp files left behind (atomic write cleaned up).
        let leftovers: Vec<_> = std::fs::read_dir(&repo)
            .expect("read dir")
            .flatten()
            .filter(|e| e.file_name().to_string_lossy().contains("varde-apply-tmp"))
            .collect();
        assert!(leftovers.is_empty(), "no tmp files: {leftovers:?}");

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn scan_with_apply_preserves_variadic_statement_and_argument_separators() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-apply-variadic-separators");
        let repo = tempdir("repo-apply-variadic-separators");
        write(&repo.join("main.ts"), TS_WITH_VARIADIC_CAPTURES);
        write(
            &repo.join(".varde-code/rules/pack.toml"),
            VARIADIC_REWRITE_RULE_PACK,
        );
        let _home_override = with_fresh_db(&home, &repo);
        git_init_and_commit(&repo);

        let input = serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        });
        let payload = scan_repo(&input).expect("apply scan succeeds");
        assert_eq!(
            payload["rewrite_summary"],
            serde_json::json!({ "applied": 2 })
        );
        assert_eq!(
            std::fs::read_to_string(repo.join("main.ts")).expect("reads"),
            "function after() { first();\n  second(); }\nafter(alpha ,\n  beta);\n"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn scan_with_apply_skips_dirty_file_and_applies_clean_sibling() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-apply-dirty");
        let repo = tempdir("repo-apply-dirty");
        write(&repo.join("clean.ts"), TS_WITH_TRACE);
        write(&repo.join("dirty.ts"), TS_WITH_TRACE);
        write(&repo.join(".varde-code/rules/pack.toml"), REWRITE_RULE_PACK);
        let _home_override = with_fresh_db(&home, &repo);
        git_init_and_commit(&repo);

        // Make dirty.ts dirty after the commit (uncommitted change).
        write(
            &repo.join("dirty.ts"),
            &format!("{TS_WITH_TRACE}\n// uncommitted\n"),
        );
        let dirty_before = std::fs::read_to_string(repo.join("dirty.ts")).expect("reads");

        let input = serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        });
        let payload = scan_repo(&input).expect("apply scan succeeds");
        let findings = payload["findings"].as_array().expect("findings array");
        // Both files match; the scan runs regardless of git state.
        assert_eq!(findings.len(), 2, "both files found: {findings:?}");
        // Envelope: clean finding applied, dirty finding skipped-dirty.
        let applied = findings
            .iter()
            .find(|f| f["rewrite_status"] == "applied")
            .expect("clean file applied");
        assert!(
            applied["location"]["file"]
                .as_str()
                .unwrap()
                .ends_with("clean.ts")
        );
        let skipped = findings
            .iter()
            .find(|f| f["rewrite_status"] == "skipped-dirty")
            .expect("dirty file skipped");
        assert!(
            skipped["location"]["file"]
                .as_str()
                .unwrap()
                .ends_with("dirty.ts")
        );
        assert_eq!(
            payload["rewrite_summary"],
            serde_json::json!({ "applied": 1, "skipped-dirty": 1 })
        );

        // Clean file was rewritten; dirty file skipped untouched.
        let clean = std::fs::read_to_string(repo.join("clean.ts")).expect("reads");
        assert!(
            clean.contains("console.info(\"async log\")"),
            "clean file applied: {clean}"
        );
        assert_eq!(
            std::fs::read_to_string(repo.join("dirty.ts")).expect("reads"),
            dirty_before,
            "dirty file not written without --force"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    /// H1 regression: a finding whose `matched_file_state` disagrees with
    /// the file's current on-disk state (it changed after matching, before
    /// `--apply` gets to it) is skipped as a conflict rather than spliced —
    /// even though its byte offsets still land in range on the new content.
    #[test]
    fn apply_skips_finding_whose_file_changed_since_it_was_matched() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-apply-stale");
        let (repo, _home_override) = setup_apply_repo("repo-apply-stale", &home, TS_WITH_TRACE);
        git_init_and_commit(&repo);

        let (rules, _diags) = crate::rules::load_rules(&repo);
        let file_path = repo.join("main.ts");
        let content_before = std::fs::read_to_string(&file_path).expect("reads");
        let trace_at = content_before
            .find("console.trace")
            .expect("fixture has a trace call");
        let span = crate::model::Span {
            start_byte: trace_at as u32,
            end_byte: (trace_at + "console.trace".len()) as u32,
            start_line: 3,
            start_col: 2,
            end_line: 3,
            end_col: 2 + "console.trace".len() as u32,
        };
        // A `matched_file_state` that does not describe the file as it
        // exists on disk right now — standing in for "matched, then the
        // file changed before apply got here" without needing a genuine
        // race. The len deliberately disagrees with the real file.
        let stale_state = crate::rules::finding::FileState {
            mtime: std::fs::metadata(&file_path)
                .expect("stat")
                .modified()
                .expect("mtime"),
            len: content_before.len() as u64 + 1,
        };
        let finding = crate::rules::finding::Finding {
            id: "stale-test".to_string(),
            rule_id: "no-console".to_string(),
            severity: Severity::Warning,
            message: "console call detected".to_string(),
            location: crate::rules::finding::Location {
                file: file_path.display().to_string(),
                span,
            },
            evidence: serde_json::json!({}),
            remediation: None,
            certainty: None,
            agent_instructions: None,
            rewrite_status: None,
            matched_file_state: Some(stale_state),
        };

        for force in [false, true] {
            let statuses = apply_rewrites(&rules, std::slice::from_ref(&finding), &repo, force)
                .expect("apply_rewrites runs");
            assert_eq!(
                statuses.get("stale-test"),
                Some(&RewriteStatus::SkippedConflict),
                "force={force}"
            );
            // File untouched after the post-read state guard.
            assert_eq!(
                std::fs::read_to_string(&file_path).expect("reads"),
                content_before,
                "file must be untouched when the match-time state is stale"
            );
        }

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    /// H2 regression: `GitGate::recheck_dirty` catches a file that became
    /// dirty after the batched probe `git_gate` ran — the exact window
    /// between the one-shot status call and this file's own write.
    #[test]
    fn recheck_dirty_catches_a_file_dirtied_after_the_batched_probe() {
        let home = tempdir("home-recheck-dirty");
        let repo = tempdir("repo-recheck-dirty");
        write(&repo.join("main.ts"), TS_WITH_TRACE);
        git_init_and_commit(&repo);
        let _ = std::fs::remove_dir_all(&home);

        let real = std::fs::canonicalize(repo.join("main.ts")).expect("canonicalize");
        let gate = git_gate(&repo, std::slice::from_ref(&real));
        assert!(!gate.dirty(&real), "clean at probe time");

        // The file becomes dirty *after* the batched probe — simulating an
        // edit landing in the window between the gate and this file's write.
        write(
            &repo.join("main.ts"),
            &format!("{TS_WITH_TRACE}\n// edited after probe\n"),
        );

        assert!(
            !gate.dirty(&real),
            "the stale batched result alone would miss this"
        );
        assert!(
            gate.recheck_dirty(&real),
            "a fresh per-file check must catch the post-probe edit"
        );

        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn apply_exit_gate_applied_error_is_resolved_skipped_is_not() {
        let _guard = crate::test_support::home_lock();

        // Applied: error-severity finding fixed in place → gate passes.
        let home = tempdir("home-gate-applied");
        let repo = tempdir("repo-gate-applied");
        write(&repo.join("main.ts"), TS_WITH_TRACE);
        write(
            &repo.join(".varde-code/rules/pack.toml"),
            REWRITE_RULE_PACK_ERROR,
        );
        let _home_override = with_fresh_db(&home, &repo);
        git_init_and_commit(&repo);
        let payload = scan_repo(&serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        }))
        .expect("apply scan succeeds");
        assert_eq!(payload["findings"][0]["rewrite_status"], "applied");
        // run_scan's gate over the emitted envelope: no unresolved error.
        assert!(!unresolved_findings_at_or_above(&payload, Severity::Error));
        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);

        // Skipped: error finding left untouched (dirty file) → gate fails.
        let home = tempdir("home-gate-skipped");
        let repo = tempdir("repo-gate-skipped");
        write(&repo.join("main.ts"), TS_WITH_TRACE);
        write(
            &repo.join(".varde-code/rules/pack.toml"),
            REWRITE_RULE_PACK_ERROR,
        );
        let _home_override = with_fresh_db(&home, &repo);
        git_init_and_commit(&repo);
        write(
            &repo.join("main.ts"),
            &format!("{TS_WITH_TRACE}\n// dirty\n"),
        );
        let payload = scan_repo(&serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        }))
        .expect("apply scan succeeds");
        assert_eq!(payload["findings"][0]["rewrite_status"], "skipped-dirty");
        assert!(unresolved_findings_at_or_above(&payload, Severity::Error));
        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn scan_output_omits_rewrite_status_for_findings_without_rewrite() {
        // SQL-rule findings and rewrite-less pattern findings keep their old
        // shape: no `rewrite_status` key (not `null`) even in an apply run.
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-no-status");
        let repo = tempdir("repo-no-status");
        write(&repo.join("main.ts"), TS_WITH_TRACE);
        write(
            &repo.join(".varde-code/rules/pack.toml"),
            r#"
[[rule]]
id = "plain-pattern"
kind = "pattern"
severity = "warning"
message = "plain pattern, no rewrite"
pattern = "console.trace($MSG)"

[[rule]]
id = "function-count"
kind = "sql"
severity = "error"
message = "function present"
query = "SELECT f.path AS file, e.start_line AS line FROM entities e JOIN files f ON f.id = e.file_id WHERE e.kind = 0"
"#,
        );
        let _home_override = with_fresh_db(&home, &repo);

        let payload = scan_repo(&serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        }))
        .expect("apply scan succeeds");
        let findings = payload["findings"].as_array().expect("findings array");
        assert!(findings.len() >= 2, "both engines fire: {findings:?}");
        for f in findings {
            assert!(
                f.get("rewrite_status").is_none(),
                "no rewrite_status on rewrite-less finding: {f:?}"
            );
        }
        assert!(
            payload.get("rewrite_summary").is_none(),
            "no summary when nothing was applied"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn scan_with_apply_and_force_writes_dirty_file() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-apply-force");
        let (repo, _home_override) = setup_apply_repo("repo-apply-force", &home, TS_WITH_TRACE);
        git_init_and_commit(&repo);
        // Dirty the file after the commit.
        write(
            &repo.join("main.ts"),
            &format!("{TS_WITH_TRACE}\n// uncommitted\n"),
        );

        let input = serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
            "force": true,
        });
        let payload = scan_repo(&input).expect("force apply scan succeeds");
        assert_eq!(payload["findings"].as_array().expect("array").len(), 1);

        let rewritten = std::fs::read_to_string(repo.join("main.ts")).expect("reads");
        assert!(
            rewritten.contains("console.info(\"async log\")"),
            "dirty file written with --force: {rewritten}"
        );
        assert!(
            rewritten.contains("// uncommitted"),
            "uncommitted tail preserved (byte-exact outside span): {rewritten}"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    /// A path to `path` relative to the process cwd — lets a test pass a
    /// *relative* `repoRoot` (which `scan_repo` must handle, CORRECTNESS-002)
    /// without mutating the process cwd (tests run in parallel threads).
    fn rel_from_cwd(path: &std::path::Path) -> std::path::PathBuf {
        let cwd = std::env::current_dir().expect("process cwd");
        let abs = if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::path::absolute(path).expect("path absolutizes")
        };
        let cwd_comp: Vec<_> = cwd.components().collect();
        let abs_comp: Vec<_> = abs.components().collect();
        let mut common = 0;
        while common < cwd_comp.len()
            && common < abs_comp.len()
            && cwd_comp[common] == abs_comp[common]
        {
            common += 1;
        }
        let mut out = std::path::PathBuf::new();
        for _ in common..cwd_comp.len() {
            out.push("..");
        }
        for comp in &abs_comp[common..] {
            out.push(comp.as_os_str());
        }
        out
    }

    #[test]
    fn apply_with_relative_repo_root_still_gates_dirty_files() {
        // CORRECTNESS-002: with a relative repoRoot, the old per-file git
        // call resolved the file path against repo_root a second time
        // (pathspec "sub/a.ts" from cwd "sub" → missing), so every dirty
        // file came back clean and was written without --force. The gate
        // must detect dirty files whether repoRoot is absolute or relative.
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-relroot");
        let repo = tempdir("repo-relroot");
        write(&repo.join("clean.ts"), TS_WITH_TRACE);
        write(&repo.join("dirty.ts"), TS_WITH_TRACE);
        write(&repo.join(".varde-code/rules/pack.toml"), REWRITE_RULE_PACK);
        let _home_override = with_fresh_db(&home, &repo);
        git_init_and_commit(&repo);
        // Dirty one file after the commit.
        write(
            &repo.join("dirty.ts"),
            &format!("{TS_WITH_TRACE}\n// uncommitted\n"),
        );
        let dirty_before = std::fs::read_to_string(repo.join("dirty.ts")).expect("reads");

        let rel = rel_from_cwd(&repo);
        let payload = scan_repo(&serde_json::json!({
            "repoRoot": rel.display().to_string(),
            "apply": true,
        }))
        .expect("apply scan with relative repoRoot succeeds");
        let findings = payload["findings"].as_array().expect("findings array");
        assert_eq!(findings.len(), 2, "both files found: {findings:?}");
        let skipped = findings
            .iter()
            .find(|f| f["rewrite_status"] == "skipped-dirty")
            .expect("dirty file skipped even with a relative repoRoot");
        assert!(
            skipped["location"]["file"]
                .as_str()
                .unwrap()
                .ends_with("dirty.ts")
        );
        let applied = findings
            .iter()
            .find(|f| f["rewrite_status"] == "applied")
            .expect("clean sibling still applied");
        assert!(
            applied["location"]["file"]
                .as_str()
                .unwrap()
                .ends_with("clean.ts")
        );
        assert_eq!(
            std::fs::read_to_string(repo.join("dirty.ts")).expect("reads"),
            dirty_before,
            "dirty file not written without --force"
        );
        assert!(
            std::fs::read_to_string(repo.join("clean.ts"))
                .expect("reads")
                .contains("console.info"),
            "clean sibling rewritten"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn apply_without_git_repo_treats_files_clean_and_writes() {
        // Documented scope (CORRECTNESS-005): outside any git repo there is
        // no git state to be undone against, so files are clean and written.
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-nogit");
        let (repo, _home_override) = setup_apply_repo("repo-nogit", &home, TS_WITH_TRACE);
        // No git_init_and_commit: the repo dir has no .git.

        let payload = scan_repo(&serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        }))
        .expect("apply scan without git succeeds");
        assert_eq!(
            payload["findings"][0]["rewrite_status"], "applied",
            "not-a-repo → clean → applied: {payload:?}"
        );
        assert!(
            std::fs::read_to_string(repo.join("main.ts"))
                .expect("reads")
                .contains("console.info"),
            "file written"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn apply_with_corrupt_git_index_fails_closed_and_skips_files() {
        // CORRECTNESS-005: a genuine git failure (corrupt index) must fail
        // closed — every file skipped-dirty, nothing written — rather than
        // silently treating the repo as clean.
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-corrupt");
        let (repo, _home_override) = setup_apply_repo("repo-corrupt", &home, TS_WITH_TRACE);
        git_init_and_commit(&repo);
        // Poison the index: `git rev-parse` still works, `git status` errors.
        std::fs::write(repo.join(".git/index"), b"not an index").expect("index overwritten");
        let before = std::fs::read_to_string(repo.join("main.ts")).expect("reads");

        let payload = scan_repo(&serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        }))
        .expect("apply scan with corrupt git index succeeds");
        let findings = payload["findings"].as_array().expect("findings array");
        assert!(
            findings
                .iter()
                .all(|f| f["rewrite_status"] == "skipped-dirty"),
            "every finding skipped on git failure: {findings:?}"
        );
        assert_eq!(
            std::fs::read_to_string(repo.join("main.ts")).expect("reads"),
            before,
            "nothing written when the git gate cannot run"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn apply_preserves_file_permission_bits() {
        // CORRECTNESS-001: the atomic write must preserve the original
        // file's mode — an executable stays executable, a read-only file
        // stays read-only (both rewritten in place).
        use std::os::unix::fs::PermissionsExt;
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-perms");
        let repo = tempdir("repo-perms");
        write(&repo.join("exec.ts"), TS_WITH_TRACE);
        write(&repo.join("ro.ts"), TS_WITH_TRACE);
        write(&repo.join(".varde-code/rules/pack.toml"), REWRITE_RULE_PACK);
        let _home_override = with_fresh_db(&home, &repo);
        // Set modes BEFORE the commit so the worktree stays clean (a mode
        // change after the commit would itself be a git change → skipped).
        std::fs::set_permissions(repo.join("exec.ts"), std::fs::Permissions::from_mode(0o755))
            .expect("chmod +x");
        std::fs::set_permissions(repo.join("ro.ts"), std::fs::Permissions::from_mode(0o444))
            .expect("chmod 444");
        git_init_and_commit(&repo);

        let payload = scan_repo(&serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        }))
        .expect("apply scan succeeds");
        let findings = payload["findings"].as_array().expect("findings array");
        assert_eq!(findings.len(), 2, "both files found: {findings:?}");
        assert!(
            findings.iter().all(|f| f["rewrite_status"] == "applied"),
            "both clean files applied: {findings:?}"
        );

        let mode = |p: &std::path::Path| {
            std::fs::metadata(p).expect("metadata").permissions().mode() & 0o777
        };
        assert_eq!(
            mode(&repo.join("exec.ts")),
            0o755,
            "executable bit preserved"
        );
        assert_eq!(mode(&repo.join("ro.ts")), 0o444, "read-only mode preserved");
        assert!(
            std::fs::read_to_string(repo.join("exec.ts"))
                .expect("reads")
                .contains("console.info"),
            "exec fixture rewritten"
        );
        assert!(
            std::fs::read_to_string(repo.join("ro.ts"))
                .expect("reads")
                .contains("console.info"),
            "read-only fixture rewritten"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn apply_rewrites_symlink_target_preserving_the_link() {
        // CORRECTNESS-004: a symlinked file's rewrite must land on the real
        // target (canonicalize-then-write) and leave the link itself alone —
        // never silently de-symlink the entry.
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-symlink");
        let repo = tempdir("repo-symlink");
        write(&repo.join("real.ts"), TS_WITH_TRACE);
        std::os::unix::fs::symlink(repo.join("real.ts"), repo.join("link.ts")).expect("symlink");
        write(&repo.join(".varde-code/rules/pack.toml"), REWRITE_RULE_PACK);
        let _home_override = with_fresh_db(&home, &repo);
        git_init_and_commit(&repo);

        let payload = scan_repo(&serde_json::json!({
            "repoRoot": repo.display().to_string(),
            "apply": true,
        }))
        .expect("apply scan succeeds");
        let findings = payload["findings"].as_array().expect("findings array");
        assert_eq!(findings.len(), 2, "link + real both found: {findings:?}");
        // The link survives as a symlink pointing at the same target…
        let link_meta = std::fs::symlink_metadata(repo.join("link.ts")).expect("link metadata");
        assert!(
            link_meta.file_type().is_symlink(),
            "link is not de-symlinked"
        );
        assert_eq!(
            std::fs::read_link(repo.join("link.ts")).expect("read_link"),
            repo.join("real.ts"),
            "link still points at real.ts"
        );
        // …and the real target was rewritten exactly once, no corruption.
        let rewritten = std::fs::read_to_string(repo.join("real.ts")).expect("reads");
        assert!(
            rewritten.contains("console.info(\"async log\")"),
            "real target rewritten: {rewritten}"
        );
        assert!(
            !rewritten.contains("console.trace"),
            "no trace remains: {rewritten}"
        );
        assert_eq!(
            rewritten.matches("console.info").count(),
            1,
            "single rewrite, no double-apply corruption: {rewritten}"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn fresh_db_runs_both_rule_kinds_and_merges_output() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home");
        let repo = tempdir("repo");
        write(&repo.join("main.ts"), TS_FIXTURE);
        write(&repo.join(".varde-code/rules/pack.toml"), RULE_PACK);
        let _home_override = with_fresh_db(&home, &repo);

        let input = serde_json::json!({ "repoRoot": repo.display().to_string() });
        let payload = scan_repo(&input).expect("scan succeeds");
        let findings = payload["findings"].as_array().expect("findings array");
        let diagnostics = payload["diagnostics"]
            .as_array()
            .expect("diagnostics array");

        let pattern_ids: Vec<&str> = findings
            .iter()
            .filter(|f| f["rule_id"] == "no-console")
            .map(|f| f["rule_id"].as_str().unwrap())
            .collect();
        let sql_ids: Vec<&str> = findings
            .iter()
            .filter(|f| f["rule_id"] == "function-count")
            .map(|f| f["rule_id"].as_str().unwrap())
            .collect();
        assert_eq!(pattern_ids.len(), 1, "pattern rule matches: {findings:?}");
        assert_eq!(sql_ids.len(), 1, "sql rule matches the persisted entity");
        assert_eq!(findings.len(), 2, "both engines' findings merged");

        let sql_finding = findings
            .iter()
            .find(|f| f["rule_id"] == "function-count")
            .unwrap();
        assert!(
            sql_finding["location"]["file"]
                .as_str()
                .unwrap()
                .ends_with("main.ts")
        );
        assert_eq!(sql_finding["severity"], "error");
        assert_eq!(sql_finding["certainty"], serde_json::Value::Null);

        assert!(
            diagnostics.is_empty(),
            "no diagnostics on a clean run: {diagnostics:?}"
        );

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn missing_db_builds_on_read_then_scans() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-empty");
        let repo = tempdir("repo-empty");
        write(&repo.join(".varde-code/rules/pack.toml"), RULE_PACK);
        // No build → no DB under the conventional path; scan must build-on-read.

        let input = serde_json::json!({ "repoRoot": repo.display().to_string() });
        let payload = scan_repo(&input).expect("missing db self-builds and scans");
        assert!(payload["findings"].as_array().expect("array").is_empty());
        assert!(payload["diagnostics"].as_array().expect("array").is_empty());

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn stale_db_self_freshens_and_matches_build_scan() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-stale");
        let repo = tempdir("repo-stale");
        write(&repo.join("main.ts"), TS_FIXTURE);
        write(&repo.join(".varde-code/rules/pack.toml"), RULE_PACK);
        let _home_override = with_fresh_db(&home, &repo);

        // Modify the source after the build → the DB is now stale.
        write(
            &repo.join("main.ts"),
            &format!("{TS_FIXTURE}\n// touched\n"),
        );

        let input = serde_json::json!({ "repoRoot": repo.display().to_string() });
        let freshened = scan_repo(&input).expect("stale db self-freshens and scans");

        // Parity: a fresh build + scan must produce the identical payload.
        let _home_override = with_fresh_db(&home, &repo);
        let rebuilt = scan_repo(&input).expect("build+scan succeeds");
        assert_eq!(freshened, rebuilt, "freshen-then-scan matches build+scan");

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn rules_list_tags_builtin_override_and_custom() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("rules-list-home");
        let _home_override = crate::test_support::HomeOverride::while_locked(&home);
        let repo = tempdir("rules-list-repo");
        write(
            &repo.join(".varde-code/rules/pack.toml"),
            r#"
[[rule]]
id = "churn-complexity-hotspot"
kind = "sql"
severity = "error"
message = "repo override of the built-in"
query = "SELECT path AS file, 1 AS line FROM files WHERE complexity > :max_complexity"
thresholds = { max_complexity = 1.0 }
strings = { scope = "production" }
fix = "Review this repository's chosen threshold."

[[rule]]
id = "no-console"
kind = "pattern"
severity = "warning"
message = "custom repo-only rule"
pattern = "console.log($MSG)"
languages = ["typescript"]
constraints = { MSG = "^message$" }
exclude_test_paths = true
exclude_tooling_paths = false
remediation = "Use the configured logger."
rewrite = "logger.info($MSG)"
"#,
        );

        let input = serde_json::json!({ "repoRoot": repo.display().to_string() });
        let payload = rules_list(&input).expect("rules_list succeeds without a DB");
        let rules = payload["rules"].as_array().expect("rules array");
        assert!(payload["diagnostics"].as_array().expect("array").is_empty());

        let by_id = |id: &str| rules.iter().find(|r| r["id"] == id).expect("rule present");
        assert_eq!(by_id("churn-complexity-hotspot")["source"], "override");
        assert_eq!(by_id("no-console")["source"], "custom");
        assert_eq!(by_id("file-complexity-hotspot")["source"], "builtin");

        let overridden = by_id("churn-complexity-hotspot");
        assert_eq!(overridden["severity"], "error");
        assert_eq!(
            overridden["thresholds"],
            serde_json::json!({"max_complexity": 1.0})
        );
        assert_eq!(
            overridden["strings"],
            serde_json::json!({"scope": "production"})
        );
        assert_eq!(
            overridden["fix"],
            "Review this repository's chosen threshold."
        );
        assert_eq!(
            overridden["query"],
            "SELECT path AS file, 1 AS line FROM files WHERE complexity > :max_complexity"
        );
        assert!(overridden.get("pattern").is_none());
        // Keep the original listing's nullable display fields for clients.
        assert_eq!(overridden.get("name"), Some(&serde_json::Value::Null));
        assert_eq!(
            overridden.get("description"),
            Some(&serde_json::Value::Null)
        );

        let custom = by_id("no-console");
        assert_eq!(custom["pattern"], "console.log($MSG)");
        assert_eq!(custom["languages"], serde_json::json!(["typescript"]));
        assert_eq!(
            custom["constraints"],
            serde_json::json!({"MSG": "^message$"})
        );
        assert_eq!(custom["exclude_test_paths"], true);
        assert_eq!(custom["exclude_tooling_paths"], false);
        assert_eq!(custom["remediation"], "Use the configured logger.");
        assert_eq!(custom["rewrite"], "logger.info($MSG)");
        assert!(custom.get("query").is_none());
        assert!(custom.get("fix").is_none());
        assert!(custom.get("tests").is_none());

        let gate = by_id("function-complexity-gate");
        assert_eq!(gate["thresholds"]["max_cognitive"], 15.0);
        assert!(gate["query"].as_str().unwrap().contains("function_metrics"));
        assert!(gate.get("languages").is_none());
        assert_eq!(payload, rules_list(&input).expect("repeat listing"));

        assert_eq!(
            rules.len(),
            crate::rules::builtin_rules().len() + 1,
            "every built-in id present once (one overridden, not duplicated) plus the custom rule"
        );

        let _ = std::fs::remove_dir_all(&repo);
        let _ = std::fs::remove_dir_all(&home);
    }

    #[test]
    fn rules_list_tags_seeded_builtin_as_override() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("rules-list-seeded-home");
        let _home_override = crate::test_support::HomeOverride::while_locked(&home);
        let repo = tempdir("rules-list-seeded-repo");
        crate::rules::seed_builtin_rules(&repo.join(".varde-code/rules"), false)
            .expect("seed built-ins");

        let input = serde_json::json!({ "repoRoot": repo.display().to_string() });
        let payload = rules_list(&input).expect("rules_list succeeds");
        let rule = payload["rules"]
            .as_array()
            .expect("rules array")
            .iter()
            .find(|rule| rule["id"] == "churn-complexity-hotspot")
            .expect("seeded rule present");
        assert_eq!(rule["source"], "override");

        let _ = std::fs::remove_dir_all(&repo);
        let _ = std::fs::remove_dir_all(&home);
    }

    #[test]
    fn rules_list_requires_no_db_and_rejects_bad_repo_root() {
        let input = serde_json::json!({ "repoRoot": "/definitely/not/a/real/path" });
        let err = rules_list(&input).expect_err("missing repo root is an error");
        assert_eq!(err.code, "invalid_input");
    }

    #[test]
    fn empty_rule_pack_is_a_valid_noop_scan() {
        let _guard = crate::test_support::home_lock();
        let home = tempdir("home-norules");
        let repo = tempdir("repo-norules");
        write(&repo.join("main.ts"), TS_FIXTURE);
        let _home_override = with_fresh_db(&home, &repo);

        let input = serde_json::json!({ "repoRoot": repo.display().to_string() });
        let payload = scan_repo(&input).expect("empty pack scans cleanly");
        assert!(payload["findings"].as_array().expect("array").is_empty());
        assert!(payload["diagnostics"].as_array().expect("array").is_empty());

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&repo);
    }
}

#[cfg(test)]
mod git_gate {
    use super::*;
    use std::collections::HashSet;
    use std::path::{Path, PathBuf};

    fn tempdir(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("varde-gitgate-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        dir
    }

    fn git(repo: &Path, args: &[&str]) {
        let status = std::process::Command::new("git")
            .args(args)
            .current_dir(repo)
            .status()
            .expect("git runs");
        assert!(status.success(), "git {args:?} failed");
    }

    fn init_and_commit(repo: &Path) {
        git(repo, &["init", "-q"]);
        git(repo, &["config", "user.email", "t@example.com"]);
        git(repo, &["config", "user.name", "test"]);
        git(repo, &["add", "-A"]);
        git(repo, &["commit", "-q", "-m", "init"]);
    }

    fn file(repo: &Path, name: &str) -> PathBuf {
        let p = repo.join(name);
        std::fs::write(&p, "content\n").expect("file writes");
        p
    }

    /// The dirty set for `targets` in `repo` (assumes a healthy work tree).
    fn dirty_set(repo: &Path, targets: &[PathBuf]) -> HashSet<PathBuf> {
        match git_gate(repo, targets) {
            GitGate::WorkTree(_, set) => set,
            GitGate::NotAGitRepo => panic!("expected a work tree"),
            GitGate::Unverifiable => panic!("expected a clean status run"),
        }
    }

    #[test]
    fn not_a_git_repo_is_clean() {
        let repo = tempdir("norepo");
        let f = file(&repo, "a.ts");
        assert!(matches!(git_gate(&repo, &[f]), GitGate::NotAGitRepo));
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn clean_tracked_file_is_not_dirty() {
        let repo = tempdir("clean");
        let f = file(&repo, "a.ts");
        init_and_commit(&repo);
        assert!(dirty_set(&repo, &[f]).is_empty());
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn modified_tracked_file_is_dirty() {
        let repo = tempdir("modified");
        let f = file(&repo, "a.ts");
        init_and_commit(&repo);
        std::fs::write(&f, "changed\n").expect("modifies");
        let real = std::fs::canonicalize(&f).expect("canonical");
        assert_eq!(
            dirty_set(&repo, &[f]),
            HashSet::from([real]),
            "modified tracked file reported dirty"
        );
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn staged_file_is_dirty() {
        let repo = tempdir("staged");
        let f = file(&repo, "a.ts");
        init_and_commit(&repo);
        std::fs::write(&f, "staged change\n").expect("modifies");
        git(&repo, &["add", "a.ts"]);
        assert!(!dirty_set(&repo, &[f]).is_empty(), "staged file is dirty");
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn untracked_file_is_dirty() {
        let repo = tempdir("untracked");
        file(&repo, "keep.ts");
        init_and_commit(&repo);
        let f = file(&repo, "new.ts");
        assert!(
            !dirty_set(&repo, &[f]).is_empty(),
            "untracked file is dirty"
        );
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn gitignored_file_is_dirty() {
        // CORRECTNESS-003: a git-ignored (untracked + .gitignore-matched)
        // file must not bypass the dirty gate — `git status` only lists it
        // with --ignored, which the batched status call passes.
        let repo = tempdir("ignored");
        file(&repo, "keep.ts");
        init_and_commit(&repo);
        std::fs::write(repo.join(".gitignore"), "gen.ts\n").expect("gitignore writes");
        git(&repo, &["add", ".gitignore"]);
        git(&repo, &["commit", "-q", "-m", "ignore"]);
        let f = file(&repo, "gen.ts");
        assert!(
            !dirty_set(&repo, &[f]).is_empty(),
            "ignored untracked file is dirty"
        );
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn corrupt_index_gates_every_file_dirty() {
        // CORRECTNESS-005: a genuine git failure (corrupt index) must fail
        // closed — every file dirty — not silently clean.
        let repo = tempdir("corrupt");
        let f = file(&repo, "a.ts");
        init_and_commit(&repo);
        std::fs::write(repo.join(".git/index"), b"garbage index").expect("index overwritten");
        assert!(matches!(git_gate(&repo, &[f]), GitGate::Unverifiable));
        let _ = std::fs::remove_dir_all(&repo);
    }

    #[test]
    fn target_outside_work_tree_is_not_gated() {
        // A symlink target outside the work tree has no git state to gate
        // against — clean, same rationale as not-a-repo.
        let repo = tempdir("outside");
        file(&repo, "keep.ts");
        init_and_commit(&repo);
        let outside = tempdir("outside-target");
        std::fs::write(outside.join("real.ts"), "x\n").expect("writes");
        std::os::unix::fs::symlink(outside.join("real.ts"), repo.join("link.ts")).expect("symlink");
        let real = std::fs::canonicalize(repo.join("link.ts")).expect("canonical");
        assert!(
            matches!(git_gate(&repo, &[real]), GitGate::WorkTree(..)),
            "outside-worktree target is not gated"
        );
        let _ = std::fs::remove_dir_all(&repo);
        let _ = std::fs::remove_dir_all(&outside);
    }
}

#[cfg(test)]
mod clone_collapse {
    use super::*;
    use crate::model::Span;
    use crate::rules::Severity;
    use crate::rules::finding::{Finding, Location};

    fn clone_member(file: &str, start_line: u32, label: &str) -> Finding {
        Finding {
            id: format!("{file}-{start_line}"),
            rule_id: CLONE_RULE_ID.to_string(),
            severity: Severity::Warning,
            message: "duplicated code".to_string(),
            location: Location {
                file: file.to_string(),
                span: Span {
                    start_byte: 0,
                    end_byte: 0,
                    start_line,
                    start_col: 0,
                    end_line: start_line + 5,
                    end_col: 0,
                },
            },
            evidence: serde_json::json!({ "label": label }),
            remediation: Some("extract shared code".to_string()),
            certainty: None,
            agent_instructions: None,
            rewrite_status: None,
            matched_file_state: None,
        }
    }

    fn other(rule_id: &str, file: &str) -> Finding {
        Finding {
            rule_id: rule_id.to_string(),
            evidence: serde_json::json!({}),
            ..clone_member(file, 1, "n/a")
        }
    }

    /// F3: same-band clone members collapse into ONE finding listing all
    /// members; a second band stays separate; non-clone findings pass through.
    #[test]
    fn collapses_bands_and_lists_members() {
        let findings = vec![
            clone_member("b.rs", 30, "clone-band-1"),
            clone_member("a.rs", 10, "clone-band-1"),
            clone_member("a.rs", 90, "clone-band-2"),
            clone_member("c.rs", 5, "clone-band-2"),
            other("file-complexity-hotspot", "big.rs"),
        ];

        let out = collapse_clone_bands(findings);

        let clones: Vec<_> = out.iter().filter(|f| f.rule_id == CLONE_RULE_ID).collect();
        assert_eq!(clones.len(), 2, "two bands -> two findings");
        assert_eq!(
            out.iter().filter(|f| f.rule_id != CLONE_RULE_ID).count(),
            1,
            "non-clone finding passes through"
        );

        let band1 = clones
            .iter()
            .find(|f| f.evidence["band"] == "clone-band-1")
            .expect("band-1 present");
        let members = band1.evidence["members"].as_array().unwrap();
        assert_eq!(members.len(), 2, "band-1 lists both members");
        // Members sorted by (file, line): a.rs before b.rs.
        assert_eq!(members[0]["file"], "a.rs");
        assert_eq!(members[0]["startLine"], 10);
        assert_eq!(members[1]["file"], "b.rs");
    }

    #[test]
    fn collapses_identical_members_across_bands() {
        let findings = vec![
            clone_member("a.rs", 10, "clone-band-1"),
            clone_member("b.rs", 20, "clone-band-1"),
            clone_member("a.rs", 10, "clone-band-2"),
            clone_member("b.rs", 20, "clone-band-2"),
        ];

        let out = collapse_clone_bands(findings);
        assert_eq!(out.len(), 1);
        assert_eq!(
            out[0].evidence["bands"],
            serde_json::json!(["clone-band-1", "clone-band-2"])
        );
    }
}

#[cfg(test)]
mod rule_legend {
    use super::*;
    use crate::rules::{Rule, RuleKind, Severity};

    fn rule(id: &str, message: &str, remediation: Option<&str>) -> Rule {
        Rule {
            id: id.to_string(),
            kind: RuleKind::Sql,
            verification: None,
            severity: Severity::Warning,
            message: message.to_string(),
            name: None,
            description: None,
            remediation: remediation.map(str::to_string),
            pattern: None,
            query: None,
            thresholds: None,
            strings: None,
            constraints: None,
            fix: None,
            rewrite: None,
            languages: None,
            exclude_test_paths: None,
            exclude_tooling_paths: None,
            test: None,
        }
    }

    /// F2: static-message + remediation are hoisted to the `rules` legend and
    /// dropped from findings; an interpolated message (differs from the rule
    /// template) is kept inline; the legend always carries the template.
    #[test]
    fn hoists_static_text_and_keeps_interpolated_message() {
        let rules = vec![
            rule("clone", "duplicated code", Some("extract the shared logic")),
            rule(
                "fat-interface",
                "'{class_name}' declares {n} methods",
                Some("split the type"),
            ),
        ];
        let mut payload = serde_json::json!({
            "findings": [
                // static: message equals the template -> dropped
                {"id": "a", "rule_id": "clone", "severity": "warning",
                 "message": "duplicated code", "remediation": "extract the shared logic",
                 "location": {"file": "a.rs"}},
                // interpolated: message differs from the template -> kept
                {"id": "b", "rule_id": "fat-interface", "severity": "warning",
                 "message": "'Foo' declares 16 methods", "remediation": "split the type",
                 "location": {"file": "b.rs"}},
            ],
            "diagnostics": [],
        });

        hoist_rule_legend(&mut payload, &rules);

        let findings = payload["findings"].as_array().unwrap();
        // Static finding: message + remediation gone.
        assert!(
            findings[0].get("message").is_none(),
            "static message dropped"
        );
        assert!(
            findings[0].get("remediation").is_none(),
            "remediation always dropped"
        );
        // Interpolated finding: rendered message stays; remediation still gone.
        assert_eq!(findings[1]["message"], "'Foo' declares 16 methods");
        assert!(findings[1].get("remediation").is_none());

        // Legend carries the template message + remediation for both rules.
        let legend = &payload["rules"];
        assert_eq!(legend["clone"]["message"], "duplicated code");
        assert_eq!(legend["clone"]["remediation"], "extract the shared logic");
        assert_eq!(
            legend["fat-interface"]["message"],
            "'{class_name}' declares {n} methods"
        );
    }
}
