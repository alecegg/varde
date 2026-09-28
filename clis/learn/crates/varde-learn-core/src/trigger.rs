//! `eval trigger`: measure a skill description's trigger accuracy against a
//! set of queries, for the claude, codex, and opencode harnesses.
//!
//! Ports `skills/eval-tools/run-evals.sh`. Codex has no documented
//! skill-invocation event, so it is scored through a substring proxy
//! implemented in [`crate::codex`] (a port of
//! `skills/eval-tools/parse-codex-trace.py`).

use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;

use crate::error::LearnError;

/// Harness a trigger eval is run against.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Harness {
    Claude,
    Codex,
    Opencode,
}

impl Harness {
    /// Lowercase CLI/flag name, e.g. for `--harness` echoes and `command -v`.
    pub fn as_str(self) -> &'static str {
        match self {
            Harness::Claude => "claude",
            Harness::Codex => "codex",
            Harness::Opencode => "opencode",
        }
    }

    /// Capitalized label used in "unusable <Harness> trace" messages,
    /// matching `parse_claude`/`parse_opencode`'s die messages.
    fn trace_label(self) -> &'static str {
        match self {
            Harness::Claude => "Claude",
            Harness::Codex => "Codex",
            Harness::Opencode => "OpenCode",
        }
    }
}

/// One query from a queries JSON file.
#[derive(Debug, Clone)]
pub struct Query {
    pub query: String,
    pub should_trigger: bool,
}

/// Inputs to a trigger eval run.
pub struct TriggerRequest {
    pub skill_name: String,
    pub queries_path: PathBuf,
    pub harness: Harness,
    pub runs: u32,
    pub skill_path: Option<PathBuf>,
}

/// Result of a trigger eval run: FAIL lines in query order, then the
/// `evals: pass=... fail=...` summary line.
pub struct TriggerReport {
    pub fail_lines: Vec<String>,
    pub summary_line: String,
    pub failed: bool,
}

const QUERIES_SHAPE_ERROR: &str =
    "queries must be a non-empty JSON array with string query and boolean should_trigger fields";

const AUTH_PHRASES: [&str; 4] = [
    "not logged in",
    "please run /login",
    "authentication required",
    "log in to continue",
];

/// Run a trigger eval for the claude, codex, or opencode harness.
pub fn run_trigger(req: &TriggerRequest) -> Result<TriggerReport, LearnError> {
    if req.runs == 0 {
        return Err(LearnError::Usage(
            "--runs must be a positive integer".to_string(),
        ));
    }
    if !req.queries_path.is_file() {
        return Err(LearnError::Usage(format!(
            "queries file not found: {}",
            req.queries_path.display()
        )));
    }
    if !cli_available(req.harness.as_str()) {
        return Err(LearnError::Usage(format!(
            "{} CLI is required",
            req.harness.as_str()
        )));
    }
    let codex_skill_path = if req.harness == Harness::Codex {
        Some(resolve_codex_skill_path(req.skill_path.as_deref())?)
    } else {
        if req.skill_path.is_some() {
            return Err(LearnError::Usage(
                "--skill-path is only used by the Codex proxy".to_string(),
            ));
        }
        None
    };

    let queries = load_queries(&req.queries_path)?;

    let mut pass = 0u32;
    let mut fail = 0u32;
    let mut fail_lines = Vec::new();

    for (index, q) in queries.iter().enumerate() {
        let query_number = index + 1;
        let mut hits = 0u32;
        for run in 1..=req.runs {
            let (stdout, stderr, status) = invoke_harness(req.harness, &q.query)?;
            if status != 0 {
                return Err(nonzero_exit_error(
                    req.harness,
                    status,
                    query_number,
                    &stderr,
                ));
            }
            let hit = match req.harness {
                Harness::Claude => parse_claude(&stdout, &req.skill_name),
                Harness::Opencode => parse_opencode(&stdout, &req.skill_name),
                Harness::Codex => crate::codex::parse_codex(
                    &stdout,
                    codex_skill_path
                        .as_deref()
                        .expect("resolved above for Harness::Codex"),
                ),
            }
            .map_err(|()| {
                LearnError::Usage(format!(
                    "unusable {} trace for query {query_number} run {run}; no score recorded",
                    req.harness.trace_label()
                ))
            })?;
            if hit {
                hits += 1;
            }
        }
        let majority = (f64::from(hits) / f64::from(req.runs)) > 0.5;
        if majority == q.should_trigger {
            pass += 1;
        } else {
            fail += 1;
            fail_lines.push(format!(
                "FAIL [harness={} want={} hits={}/{}] {}",
                req.harness.as_str(),
                q.should_trigger,
                hits,
                req.runs,
                q.query
            ));
        }
    }

    let codex_measure_suffix = if req.harness == Harness::Codex {
        " codex_measure=implicit_read_proxy"
    } else {
        ""
    };
    let summary_line = format!(
        "evals: pass={pass} fail={fail} skill={} harness={}{codex_measure_suffix}",
        req.skill_name,
        req.harness.as_str()
    );

    Ok(TriggerReport {
        fail_lines,
        summary_line,
        failed: fail > 0,
    })
}

/// Resolves `--skill-path` for the Codex proxy: required, resolved against
/// the process cwd when relative, and must name an existing file. The
/// resolved absolute path is the substring [`crate::codex::parse_codex`]
/// looks for in each completed `command_execution`.
fn resolve_codex_skill_path(skill_path: Option<&Path>) -> Result<PathBuf, LearnError> {
    let skill_path = skill_path.ok_or_else(|| {
        LearnError::Usage("Codex proxy requires --skill-path /path/to/SKILL.md".to_string())
    })?;
    let resolved = if skill_path.is_absolute() {
        skill_path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|err| LearnError::Usage(format!("cannot resolve current directory: {err}")))?
            .join(skill_path)
    };
    if !resolved.is_file() {
        return Err(LearnError::Usage(format!(
            "Codex skill path is not a file: {}",
            resolved.display()
        )));
    }
    Ok(resolved)
}

fn nonzero_exit_error(
    harness: Harness,
    status: i32,
    query_number: usize,
    stderr: &[u8],
) -> LearnError {
    let stderr_text = String::from_utf8_lossy(stderr);
    let detail = stderr_text.lines().next().unwrap_or("");
    let message = if detail.is_empty() {
        format!(
            "{} CLI exited {status} for query {query_number}",
            harness.as_str()
        )
    } else {
        format!(
            "{} CLI exited {status} for query {query_number}: {detail}",
            harness.as_str()
        )
    };
    LearnError::Usage(message)
}

fn load_queries(path: &Path) -> Result<Vec<Query>, LearnError> {
    let text = std::fs::read_to_string(path)
        .map_err(|_| LearnError::Usage(format!("queries file not found: {}", path.display())))?;
    let value: Value = serde_json::from_str(&text)
        .map_err(|_| LearnError::Usage(QUERIES_SHAPE_ERROR.to_string()))?;
    let array = value
        .as_array()
        .filter(|items| !items.is_empty())
        .ok_or_else(|| LearnError::Usage(QUERIES_SHAPE_ERROR.to_string()))?;
    array
        .iter()
        .map(|item| {
            let query = item.get("query").and_then(Value::as_str);
            let should_trigger = item.get("should_trigger").and_then(Value::as_bool);
            match (query, should_trigger) {
                (Some(query), Some(should_trigger)) => Ok(Query {
                    query: query.to_string(),
                    should_trigger,
                }),
                _ => Err(LearnError::Usage(QUERIES_SHAPE_ERROR.to_string())),
            }
        })
        .collect()
}

/// `command -v <name>`, without shelling out (which would risk launching a
/// billed session if `name` happened to resolve to something unexpected).
fn cli_available(name: &str) -> bool {
    let Some(path_var) = std::env::var_os("PATH") else {
        return false;
    };
    std::env::split_paths(&path_var).any(|dir| is_executable_file(&dir.join(name)))
}

#[cfg(unix)]
fn is_executable_file(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(path)
        .map(|meta| meta.is_file() && meta.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

#[cfg(not(unix))]
fn is_executable_file(path: &Path) -> bool {
    path.is_file()
}

fn invoke_harness(harness: Harness, query: &str) -> Result<(Vec<u8>, Vec<u8>, i32), LearnError> {
    let mut cmd = Command::new(harness.as_str());
    match harness {
        Harness::Claude => {
            cmd.args(["-p", query, "--output-format", "stream-json", "--verbose"]);
        }
        Harness::Opencode => {
            cmd.args(["run", "--format", "json", query]);
        }
        Harness::Codex => {
            cmd.args(["exec", "--json", query]);
        }
    }
    let output = cmd.output().map_err(|err| {
        LearnError::Usage(format!("failed to launch {} CLI: {err}", harness.as_str()))
    })?;
    let status = output.status.code().unwrap_or(-1);
    Ok((output.stdout, output.stderr, status))
}

pub(crate) fn contains_auth_phrase(text: &str) -> bool {
    let lower = text.to_lowercase();
    AUTH_PHRASES.iter().any(|phrase| lower.contains(phrase))
}

pub(crate) fn parse_events(trace: &[u8]) -> Result<Vec<Value>, ()> {
    let text = std::str::from_utf8(trace).map_err(|_| ())?;
    let mut events = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        events.push(serde_json::from_str(line).map_err(|_| ())?);
    }
    if events.is_empty() {
        return Err(());
    }
    Ok(events)
}

/// Port of `parse_claude` (run-evals.sh:105-120). Every jq `elif` guard
/// becomes an `Err(())`; the caller turns that into a generic "unusable
/// trace" message, so only the pass/fail shape of each check needs to
/// match, not its wording.
fn parse_claude(trace: &[u8], skill: &str) -> Result<bool, ()> {
    let events = parse_events(trace)?;

    for event in &events {
        let obj = event.as_object().ok_or(())?;
        let ty = obj.get("type").and_then(Value::as_str).ok_or(())?;
        if !["system", "assistant", "user", "result"].contains(&ty) {
            return Err(());
        }
    }

    for event in &events {
        if event.get("type").and_then(Value::as_str) != Some("assistant") {
            continue;
        }
        let message = event.get("message").and_then(Value::as_object).ok_or(())?;
        let content = message.get("content").and_then(Value::as_array).ok_or(())?;
        for item in content {
            match item.get("type").and_then(Value::as_str) {
                Some("tool_use") => {
                    let name = item.get("name").and_then(Value::as_str).ok_or(())?;
                    let input = item.get("input").and_then(Value::as_object).ok_or(())?;
                    if name == "Skill" && input.get("skill").and_then(Value::as_str).is_none() {
                        return Err(());
                    }
                }
                Some("text") => {
                    if let Some(text) = item.get("text").and_then(Value::as_str)
                        && contains_auth_phrase(text)
                    {
                        return Err(());
                    }
                }
                _ => {}
            }
        }
    }

    let assistant_count = events
        .iter()
        .filter(|event| event.get("type").and_then(Value::as_str) == Some("assistant"))
        .count();
    if assistant_count == 0 {
        return Err(());
    }

    let results: Vec<&Value> = events
        .iter()
        .filter(|event| event.get("type").and_then(Value::as_str) == Some("result"))
        .collect();
    if results.len() != 1 {
        return Err(());
    }
    let result = results[0];
    let succeeded = result.get("subtype").and_then(Value::as_str) == Some("success")
        && result.get("is_error").and_then(Value::as_bool) == Some(false);
    if !succeeded {
        return Err(());
    }

    Ok(events.iter().any(|event| {
        event.get("type").and_then(Value::as_str) == Some("assistant")
            && event
                .get("message")
                .and_then(|message| message.get("content"))
                .and_then(Value::as_array)
                .is_some_and(|content| {
                    content.iter().any(|item| {
                        item.get("type").and_then(Value::as_str) == Some("tool_use")
                            && item.get("name").and_then(Value::as_str) == Some("Skill")
                            && item
                                .get("input")
                                .and_then(|input| input.get("skill"))
                                .and_then(Value::as_str)
                                == Some(skill)
                    })
                })
    }))
}

/// Port of `parse_opencode` (run-evals.sh:123-144). See `parse_claude` for
/// the error-mapping note.
fn parse_opencode(trace: &[u8], skill: &str) -> Result<bool, ()> {
    let events = parse_events(trace)?;
    validate_opencode_types(&events)?;
    validate_opencode_parts(&events)?;
    if !opencode_has_start(&events) || !opencode_has_terminal_event(&events)? {
        return Err(());
    }
    Ok(opencode_skill_hit(&events, skill))
}

fn validate_opencode_types(events: &[Value]) -> Result<(), ()> {
    for event in events {
        let obj = event.as_object().ok_or(())?;
        let ty = obj.get("type").and_then(Value::as_str).ok_or(())?;
        if ![
            "step_start",
            "text",
            "reasoning",
            "tool_use",
            "step_finish",
            "error",
        ]
        .contains(&ty)
        {
            return Err(());
        }
        if ty == "error" {
            return Err(());
        }
    }
    Ok(())
}

fn validate_opencode_parts(events: &[Value]) -> Result<(), ()> {
    for event in events {
        let ty = event
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let part = event.get("part");
        match ty {
            "tool_use" => validate_opencode_tool(part)?,
            "step_finish" => validate_opencode_finish(part)?,
            "step_start" => validate_opencode_start(part)?,
            "text" => validate_opencode_text(part)?,
            _ => {}
        }
    }
    Ok(())
}

fn validate_opencode_tool(part: Option<&Value>) -> Result<(), ()> {
    let part = part.and_then(Value::as_object).ok_or(())?;
    if part.get("type").and_then(Value::as_str) != Some("tool") {
        return Err(());
    }
    let tool = part.get("tool").and_then(Value::as_str).ok_or(())?;
    let state = part.get("state").and_then(Value::as_object).ok_or(())?;
    if state.get("status").and_then(Value::as_str) != Some("completed") {
        return Err(());
    }
    let input = state.get("input").and_then(Value::as_object).ok_or(())?;
    if tool == "skill" && input.get("id").and_then(Value::as_str).is_none() {
        return Err(());
    }
    Ok(())
}

fn validate_opencode_finish(part: Option<&Value>) -> Result<(), ()> {
    let part = part.and_then(Value::as_object).ok_or(())?;
    if part.get("type").and_then(Value::as_str) != Some("step-finish") {
        return Err(());
    }
    let reason = part.get("reason").and_then(Value::as_str).ok_or(())?;
    if !["tool-calls", "stop"].contains(&reason) {
        return Err(());
    }
    Ok(())
}

fn validate_opencode_start(part: Option<&Value>) -> Result<(), ()> {
    let part = part.and_then(Value::as_object).ok_or(())?;
    if part.get("type").and_then(Value::as_str) != Some("step-start") {
        return Err(());
    }
    Ok(())
}

fn validate_opencode_text(part: Option<&Value>) -> Result<(), ()> {
    let part = part.and_then(Value::as_object).ok_or(())?;
    if part.get("type").and_then(Value::as_str) != Some("text") {
        return Err(());
    }
    let text = part.get("text").and_then(Value::as_str).ok_or(())?;
    if contains_auth_phrase(text) {
        return Err(());
    }
    Ok(())
}

fn opencode_has_start(events: &[Value]) -> bool {
    events
        .iter()
        .any(|event| event.get("type").and_then(Value::as_str) == Some("step_start"))
}

fn opencode_skill_hit(events: &[Value], skill: &str) -> bool {
    events.iter().any(|event| {
        event.get("type").and_then(Value::as_str) == Some("tool_use")
            && event
                .get("part")
                .and_then(|part| part.get("tool"))
                .and_then(Value::as_str)
                == Some("skill")
            && event
                .get("part")
                .and_then(|part| part.get("state"))
                .and_then(|state| state.get("input"))
                .and_then(|input| input.get("id"))
                .and_then(Value::as_str)
                == Some(skill)
    })
}

fn opencode_has_terminal_event(events: &[Value]) -> Result<bool, ()> {
    let last = events.last().ok_or(())?;
    let last_ty = last.get("type").and_then(Value::as_str);
    let last_part = last.get("part");

    let ended_at_stop = last_ty == Some("step_finish")
        && last_part
            .and_then(|part| part.get("reason"))
            .and_then(Value::as_str)
            == Some("stop");
    let ended_with_final_text = last_ty == Some("text")
        && last_part
            .and_then(|part| part.get("time"))
            .and_then(|time| time.get("end"))
            .is_some_and(|end| !end.is_null());

    Ok(ended_at_stop || ended_with_final_text)
}

#[cfg(test)]
mod tests {
    use super::parse_opencode;

    #[test]
    fn opencode_rejects_missing_skill_id_and_unfinished_final_text() {
        let start = r#"{"type":"step_start","part":{"type":"step-start"}}"#;
        let malformed_tool = r#"{"type":"tool_use","part":{"type":"tool","tool":"skill","state":{"status":"completed","input":{}}}}"#;
        let valid_tool = r#"{"type":"tool_use","part":{"type":"tool","tool":"skill","state":{"status":"completed","input":{"id":"target"}}}}"#;
        let stop = r#"{"type":"step_finish","part":{"type":"step-finish","reason":"stop"}}"#;
        let unfinished =
            r#"{"type":"text","part":{"type":"text","text":"done","time":{"end":null}}}"#;
        let finished = r#"{"type":"text","part":{"type":"text","text":"done","time":{"end":1}}}"#;
        let trace = |events: &[&str]| events.join("\n");

        assert_eq!(
            parse_opencode(trace(&[start, malformed_tool, stop]).as_bytes(), "target"),
            Err(())
        );
        assert_eq!(
            parse_opencode(trace(&[start, valid_tool, unfinished]).as_bytes(), "target"),
            Err(())
        );
        assert_eq!(
            parse_opencode(trace(&[start, valid_tool, finished]).as_bytes(), "target"),
            Ok(true)
        );
    }
}
