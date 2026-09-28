//! Deterministic `verification_script` grading and the LLM judge, ported
//! from `run_deterministic_verification()`, `run_llm_judge()`, and
//! `grade_current_run()` in `skills/eval-tools/run-output-evals.sh`.
//!
//! Writes `verification.json`, `judge-raw.json`, `judge-grading.json`, and
//! `grading.json` for one run; [`super::run::execute_run`] calls
//! [`grade_run`] after it has written `timing.json`, while the run's
//! sandbox is still on disk.

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use serde_json::{Value, json};

use crate::error::LearnError;
use crate::{ExitResult, RunOutcome as ProcessOutcome, RunRequest, run_with_timeout};

use super::adapter;
use super::run::extract_transcript;
use super::{Config, EvalCase, EvalOutcome, OutputHarness};

/// One assertion's grading result, merged from verification and judge
/// output, or synthesized when neither source covered it.
#[derive(Clone)]
struct GradeResult {
    assertion: String,
    verdict: String,
    evidence: String,
}

impl GradeResult {
    fn to_json(&self) -> Value {
        json!({"assertion": self.assertion, "verdict": self.verdict, "evidence": self.evidence})
    }

    fn fail(assertion: &str, evidence: impl Into<String>) -> Self {
        Self {
            assertion: assertion.to_string(),
            verdict: "FAIL".to_string(),
            evidence: evidence.into(),
        }
    }
}

/// How the LLM judge call ended, persisted in `grading.json.judge_outcome`.
#[derive(Clone, Copy)]
enum JudgeOutcome {
    NotRun,
    NotNeeded,
    Completed,
    Failed,
    TimedOut,
}

impl JudgeOutcome {
    fn as_str(self) -> &'static str {
        match self {
            JudgeOutcome::NotRun => "not_run",
            JudgeOutcome::NotNeeded => "not_needed",
            JudgeOutcome::Completed => "completed",
            JudgeOutcome::Failed => "failed",
            JudgeOutcome::TimedOut => "timed_out",
        }
    }
}

/// Inputs to [`grade_run`].
pub(super) struct GradeRequest<'a> {
    pub env: &'a [(String, String)],
    pub skill_dir: &'a Path,
    pub eval: &'a EvalCase,
    pub cfg: Config,
    pub run: u32,
    pub eval_run_start: u64,
    pub run_dir: &'a Path,
    pub run_dir_abs: &'a Path,
    pub sbox: &'a Path,
    pub raw_path: &'a Path,
    pub transcript: &'a str,
    pub run_outcome: EvalOutcome,
    pub timeout_seconds: u64,
    pub harness: OutputHarness,
    pub model: Option<&'a str>,
}

/// Outcome of grading a single run, enough for `benchmark.json` aggregation.
pub(super) struct GradeSummary {
    pub total: u32,
    pub passed: u32,
    pub judge_outcome: &'static str,
}

/// Ports `grade_current_run()`: deterministic verification, then the LLM
/// judge for whatever assertions remain, merged and written to
/// `grading.json` (plus `verification.json`, `judge-raw.json`,
/// `judge-grading.json`).
pub(super) fn grade_run(req: &GradeRequest) -> Result<GradeSummary, LearnError> {
    let declared = &req.eval.assertions;
    let total = declared.len() as u32;
    if total == 0 {
        write_json(
            &req.run_dir.join("grading.json"),
            &json!({
                "total": 0, "passed": 0, "results": [],
                "run_outcome": req.run_outcome.as_str(),
                "judge_outcome": "not_needed",
                "note": "no assertions yet — add after reviewing this run",
            }),
        )?;
        return Ok(GradeSummary {
            total: 0,
            passed: 0,
            judge_outcome: "not_needed",
        });
    }

    let (merged, judge_outcome) = if req.run_outcome != EvalOutcome::Completed {
        write_json(
            &req.run_dir.join("verification.json"),
            &json!({"results": []}),
        )?;
        write_json(&req.run_dir.join("judge-raw.json"), &json!({}))?;
        write_json(
            &req.run_dir.join("judge-grading.json"),
            &json!({"results": []}),
        )?;
        let evidence = if req.run_outcome == EvalOutcome::TimedOut {
            format!(
                "Evaluated run timed out after {} seconds",
                req.timeout_seconds
            )
        } else {
            "Evaluated run failed; assertions cannot pass".into()
        };
        let merged: Vec<GradeResult> = declared
            .iter()
            .map(|assertion| GradeResult::fail(assertion, evidence.clone()))
            .collect();
        (merged, JudgeOutcome::NotRun)
    } else {
        let verified = run_deterministic_verification(req, declared)?;
        let verified_set: HashSet<&str> = verified.iter().map(|r| r.assertion.as_str()).collect();
        let judge_assertions: Vec<String> = declared
            .iter()
            .filter(|a| !verified_set.contains(a.as_str()))
            .cloned()
            .collect();

        let (judged, judge_outcome) = if judge_assertions.is_empty() {
            write_json(&req.run_dir.join("judge-raw.json"), &json!({}))?;
            (Vec::new(), JudgeOutcome::NotNeeded)
        } else {
            run_llm_judge(req, &judge_assertions)?
        };
        write_json(
            &req.run_dir.join("judge-grading.json"),
            &json!({"results": judged.iter().map(GradeResult::to_json).collect::<Vec<_>>()}),
        )?;

        let mut covered = verified;
        covered.extend(judged);
        let merged: Vec<GradeResult> = declared
            .iter()
            .map(|assertion| {
                covered
                    .iter()
                    .find(|r| &r.assertion == assertion)
                    .cloned()
                    .unwrap_or_else(|| GradeResult::fail(assertion, "No grading result returned"))
            })
            .collect();
        (merged, judge_outcome)
    };

    let passed = merged.iter().filter(|r| r.verdict == "PASS").count() as u32;
    write_json(
        &req.run_dir.join("grading.json"),
        &json!({
            "total": total,
            "passed": passed,
            "results": merged.iter().map(GradeResult::to_json).collect::<Vec<_>>(),
            "run_outcome": req.run_outcome.as_str(),
            "judge_outcome": judge_outcome.as_str(),
        }),
    )?;

    Ok(GradeSummary {
        total,
        passed,
        judge_outcome: judge_outcome.as_str(),
    })
}

/// Ports `run_deterministic_verification()`: runs `verification_script`
/// (when configured) with `EVAL_*` env vars, captures its stdout to
/// `verification.json`, and validates the result shape against `declared`.
fn run_deterministic_verification(
    req: &GradeRequest,
    declared: &[String],
) -> Result<Vec<GradeResult>, LearnError> {
    let Some(script_rel) = &req.eval.verification_script else {
        write_json(
            &req.run_dir.join("verification.json"),
            &json!({"results": []}),
        )?;
        return Ok(Vec::new());
    };
    let script_path = req.skill_dir.join(script_rel);
    let output = Command::new("bash")
        .arg(&script_path)
        .current_dir(req.sbox)
        .envs(req.env.iter().map(|(key, value)| (key, value)))
        .env("EVAL_ID", &req.eval.id)
        .env("EVAL_CONFIG", req.cfg.as_str())
        .env("EVAL_RUN", req.run.to_string())
        .env("EVAL_RUN_DIR", req.run_dir_abs)
        .env(
            "EVAL_TRANSCRIPT",
            req.run_dir_abs.join("outputs").join("transcript.txt"),
        )
        .env("EVAL_SKILL_DIR", req.skill_dir)
        .env("EVAL_SANDBOX_DIR", req.sbox)
        .env("EVAL_RUN_START", req.eval_run_start.to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .output()
        .map_err(|err| LearnError::Usage(format!("failed to launch verification_script: {err}")))?;
    fs::write(req.run_dir.join("verification.json"), &output.stdout)
        .map_err(|err| LearnError::Usage(format!("failed to write verification.json: {err}")))?;
    if !output.status.success() {
        return Err(LearnError::Usage(format!(
            "verification_script failed for eval {}, {} run {}",
            req.eval.id,
            req.cfg.as_str(),
            req.run
        )));
    }

    let invalid = || {
        LearnError::Usage(format!(
            "invalid verification result for eval {}, {} run {}",
            req.eval.id,
            req.cfg.as_str(),
            req.run
        ))
    };
    let value: Value = serde_json::from_slice(&output.stdout).map_err(|_| invalid())?;
    let results = value
        .get("results")
        .and_then(Value::as_array)
        .ok_or_else(invalid)?;
    let mut seen = HashSet::new();
    let mut out = Vec::with_capacity(results.len());
    for item in results {
        let assertion = item
            .get("assertion")
            .and_then(Value::as_str)
            .ok_or_else(invalid)?;
        if !declared.iter().any(|d| d == assertion) || !seen.insert(assertion.to_string()) {
            return Err(invalid());
        }
        let verdict = item
            .get("verdict")
            .and_then(Value::as_str)
            .ok_or_else(invalid)?;
        if verdict != "PASS" && verdict != "FAIL" {
            return Err(invalid());
        }
        let evidence = item
            .get("evidence")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        out.push(GradeResult {
            assertion: assertion.to_string(),
            verdict: verdict.to_string(),
            evidence,
        });
    }
    Ok(out)
}

/// Ports `run_llm_judge()`: builds the grading prompt (expected output,
/// remaining assertions, transcript, sandbox file listing, ordered tool
/// uses), runs a separate `claude -p` under the same deadline as the
/// evaluated run, and parses its JSON envelope. A judge failure or timeout
/// does not abort the runner — the run is graded as `FAIL` for whatever the
/// judge didn't return.
fn run_llm_judge(
    req: &GradeRequest,
    judge_assertions: &[String],
) -> Result<(Vec<GradeResult>, JudgeOutcome), LearnError> {
    let assertions_json = serde_json::to_string(judge_assertions).unwrap_or_default();
    let prompt = format!(
        "You are grading an agent's output against a list of assertions. For EACH assertion, decide PASS or FAIL and cite concrete evidence quoted or referenced from the output — do not give the benefit of the doubt (a vague gesture at a requirement is a FAIL). Output ONLY a JSON object, no prose and no markdown fences, shaped exactly:\n\
{{\"results\":[{{\"assertion\":\"<verbatim>\",\"verdict\":\"PASS\"|\"FAIL\",\"evidence\":\"<quote/ref>\"}}]}}\n\
\n\
EXPECTED OUTPUT (what success looks like):\n{expected}\n\
\n\
ASSERTIONS (grade each):\n{assertions}\n\
\n\
AGENT OUTPUT (transcript to grade):\n{transcript}\n\
\n\
SANDBOX FILES AFTER THE RUN:\n{files}\n\
\n\
TOOL USES DURING THE RUN, IN ORDER:\n{tools}",
        expected = req.eval.expected_output,
        assertions = assertions_json,
        transcript = req.transcript,
        files = sandbox_file_listing(req.sbox),
        tools = tool_use_list(req.raw_path),
    );

    let args = adapter::args(req.harness, req.model, &prompt, req.sbox, true);
    let judge_raw_path = req.run_dir.join("judge-raw.json");
    let stream_path = if req.harness == OutputHarness::Codex {
        req.run_dir.join("judge-raw.jsonl")
    } else {
        judge_raw_path.clone()
    };
    let judge_stderr_path = req.run_dir.join("judge-raw.stderr.log");
    let request = RunRequest {
        program: req.harness.as_str(),
        args: &args,
        cwd: Some(req.sbox),
        env: &[],
        stdin: if req.harness == OutputHarness::Codex {
            prompt.as_bytes()
        } else {
            &[]
        },
        stdout_path: &stream_path,
        stderr_path: &judge_stderr_path,
        timeout: Duration::from_secs(req.timeout_seconds),
    };
    let outcome = run_with_timeout(&request)?;
    let mut judge_outcome = match outcome {
        ProcessOutcome::Completed(ExitResult::Code(0)) => JudgeOutcome::Completed,
        ProcessOutcome::Completed(_) => JudgeOutcome::Failed,
        ProcessOutcome::TimedOut => JudgeOutcome::TimedOut,
    };

    let (raw_value, trace_error) = adapter::read_raw(req.harness, &stream_path, &judge_raw_path)?;
    if trace_error.is_some() && matches!(judge_outcome, JudgeOutcome::Completed) {
        judge_outcome = JudgeOutcome::Failed;
    }
    if !matches!(judge_outcome, JudgeOutcome::Completed) {
        return Ok((Vec::new(), judge_outcome));
    }
    let text = raw_value
        .as_ref()
        .map(extract_transcript)
        .unwrap_or_default();
    let stripped = strip_code_fences(&text);
    let judged_value = serde_json::from_str::<Value>(&stripped)
        .ok()
        .filter(Value::is_object)
        .unwrap_or_else(|| json!({}));
    let judged: Vec<GradeResult> = judged_value
        .get("results")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(value_to_grade_result)
        .collect();
    Ok((judged, judge_outcome))
}

fn value_to_grade_result(item: &Value) -> Option<GradeResult> {
    let assertion = item.get("assertion").and_then(Value::as_str)?.to_string();
    let verdict = item.get("verdict").and_then(Value::as_str)?.to_string();
    let evidence = item
        .get("evidence")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    Some(GradeResult {
        assertion,
        verdict,
        evidence,
    })
}

/// Strips a leading ```` ```json ```` / ```` ``` ```` fence and a trailing
/// ```` ``` ```` fence, matching the shell judge's `sed` cleanup.
fn strip_code_fences(text: &str) -> String {
    let trimmed = text.trim();
    let without_prefix = trimmed
        .strip_prefix("```json")
        .or_else(|| trimmed.strip_prefix("```"))
        .unwrap_or(trimmed);
    without_prefix
        .strip_suffix("```")
        .unwrap_or(without_prefix)
        .trim()
        .to_string()
}

/// Ports `sandbox_file_listing()`: every file's path and size, plus small
/// text files (<=2000 bytes, capped at 8000 bytes total) inlined so the
/// judge can grade file-content assertions it otherwise never sees.
fn sandbox_file_listing(sbox: &Path) -> String {
    let mut files = Vec::new();
    collect_files(sbox, sbox, &mut files);
    files.sort();

    let mut out = String::new();
    let mut used = 0usize;
    for rel in files {
        let full = sbox.join(&rel);
        let size = fs::metadata(&full).map(|meta| meta.len()).unwrap_or(0);
        out.push_str(&format!("{} ({} bytes)\n", rel.display(), size));
        if size > 2000 || used >= 8000 {
            continue;
        }
        let Ok(text) = fs::read_to_string(&full) else {
            continue;
        };
        out.push_str(&format!("--- {} ---\n", rel.display()));
        out.push_str(&text);
        out.push('\n');
        used += size as usize;
    }
    out
}

fn collect_files(root: &Path, dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        if entry.file_name() == ".git" {
            continue;
        }
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        if file_type.is_dir() {
            collect_files(root, &entry.path(), out);
        } else if file_type.is_file()
            && let Ok(rel) = entry.path().strip_prefix(root)
        {
            out.push(rel.to_path_buf());
        }
    }
}

/// Ports `tool_use_list()`: the ordered `tool_use` calls (name + input) from
/// the run's `raw.json`.
fn tool_use_list(raw_path: &Path) -> String {
    let Some(value) = fs::read_to_string(raw_path)
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
    else {
        return String::new();
    };
    let calls: Vec<(String, Value)> = value
        .get("messages")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|message| message.get("content").and_then(Value::as_array))
        .flatten()
        .filter(|part| part.get("type").and_then(Value::as_str) == Some("tool_use"))
        .map(|part| {
            let name = part
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let input = part.get("input").cloned().unwrap_or(Value::Null);
            (name, input)
        })
        .collect();
    calls
        .into_iter()
        .enumerate()
        .map(|(index, (name, input))| format!("{}. {name} {input}", index + 1))
        .collect::<Vec<_>>()
        .join("\n")
}

fn write_json(path: &Path, value: &Value) -> Result<(), LearnError> {
    let encoded = serde_json::to_vec_pretty(value)
        .map_err(|err| LearnError::Usage(format!("failed to encode {}: {err}", path.display())))?;
    fs::write(path, encoded)
        .map_err(|err| LearnError::Usage(format!("failed to write {}: {err}", path.display())))
}
