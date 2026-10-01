//! Deterministic `verification_script` grading and the LLM judge, ported
//! from `run_deterministic_verification()`, `run_llm_judge()`, and
//! `grade_current_run()` in `skills/eval-tools/run-output-evals.sh`.
//!
//! Writes `verification.json`, `judge-raw.json`, `judge-grading.json`, and
//! `grading.json` for one run; [`super::run::execute_run`] calls
//! [`grade_run`] after it has written `timing.json`, while the run's
//! sandbox is still on disk.

use std::collections::HashSet;
use std::ffi::CString;
use std::fs;
use std::io::{self, Read, Write};
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use serde_json::{Value, json};

use crate::error::LearnError;
use crate::{ExitResult, RunOutcome as ProcessOutcome, RunRequest, run_with_timeout};

use super::adapter;
use super::run::extract_transcript;
use super::{Config, EvalCase, EvalOutcome, OutputHarness};

const MAX_VERIFICATION_OUTPUT_BYTES: usize = 1024 * 1024;

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
    let verification_path = req.run_dir.join("verification.json");
    let temporary_dir = tempfile::Builder::new()
        .prefix("varde-verification-")
        .tempdir_in(req.run_dir)
        .map_err(|err| {
            LearnError::Usage(format!("failed to create verification temp dir: {err}"))
        })?;
    let fifo_path = temporary_dir.path().join("stdout.fifo");
    let stderr_path = temporary_dir.path().join("stderr");
    let pgid_path = temporary_dir.path().join("process-group-id");
    let fifo_cstring = CString::new(fifo_path.as_os_str().as_bytes())
        .map_err(|err| LearnError::Usage(format!("invalid verification FIFO path: {err}")))?;
    // SAFETY: fifo_cstring is a valid NUL-terminated path, mode is valid,
    // and temporary_dir owns the path for the whole capture lifetime.
    if unsafe { libc::mkfifo(fifo_cstring.as_ptr(), 0o600) } == -1 {
        return Err(LearnError::Usage(format!(
            "failed to create verification output FIFO: {}",
            io::Error::last_os_error()
        )));
    }
    let capture_path = verification_path.clone();
    let capture_fifo_path = fifo_path.clone();
    let capture_pgid_path = pgid_path.clone();
    let capture_thread = thread::spawn(move || {
        capture_verification_output(&capture_fifo_path, &capture_path, &capture_pgid_path)
    });
    let wrapper = "printf '%s\\n' \"$$\" > \"$2\"; exec bash \"$1\"".to_string();
    let args = vec![
        "-c".to_string(),
        wrapper,
        "varde-verification".to_string(),
        script_path.display().to_string(),
        pgid_path.display().to_string(),
    ];
    let mut env = req.env.to_vec();
    env.extend([
        ("EVAL_ID".to_string(), req.eval.id.clone()),
        ("EVAL_CONFIG".to_string(), req.cfg.as_str().to_string()),
        ("EVAL_RUN".to_string(), req.run.to_string()),
        (
            "EVAL_RUN_DIR".to_string(),
            req.run_dir_abs.display().to_string(),
        ),
        (
            "EVAL_TRANSCRIPT".to_string(),
            req.run_dir_abs
                .join("outputs")
                .join("transcript.txt")
                .display()
                .to_string(),
        ),
        (
            "EVAL_SKILL_DIR".to_string(),
            req.skill_dir.display().to_string(),
        ),
        (
            "EVAL_SANDBOX_DIR".to_string(),
            req.sbox.display().to_string(),
        ),
        ("EVAL_RUN_START".to_string(), req.eval_run_start.to_string()),
    ]);
    let request = RunRequest {
        program: "bash",
        args: &args,
        cwd: Some(req.sbox),
        env: &env,
        stdin: &[],
        stdout_path: &fifo_path,
        stderr_path: &stderr_path,
        timeout: Duration::from_secs(req.timeout_seconds),
    };
    let outcome = run_with_timeout(&request);
    let process_group_cleanup = if outcome.is_ok() {
        kill_verification_process_group(&pgid_path)
    } else {
        Ok(())
    };
    let capture_result = capture_thread
        .join()
        .map_err(|_| LearnError::Usage("verification output reader panicked".to_string()))?;
    let stderr_result = forward_file_to_stderr(&stderr_path);
    stderr_result?;
    process_group_cleanup.map_err(|err| {
        LearnError::Usage(format!("failed to clean verification process group: {err}"))
    })?;
    let outcome = outcome?;
    let output_exceeded_limit = capture_result.map_err(|err| {
        LearnError::Usage(format!("failed to capture verification output: {err}"))
    })?;
    if output_exceeded_limit {
        return Err(LearnError::Usage(format!(
            "verification_script output exceeded the {MAX_VERIFICATION_OUTPUT_BYTES} byte limit for eval {}, {} run {}; return a smaller JSON result",
            req.eval.id,
            req.cfg.as_str(),
            req.run
        )));
    }
    if outcome == ProcessOutcome::TimedOut {
        return Err(LearnError::Usage(format!(
            "verification_script timed out after {} seconds for eval {}, {} run {}",
            req.timeout_seconds,
            req.eval.id,
            req.cfg.as_str(),
            req.run
        )));
    }
    if outcome != ProcessOutcome::Completed(ExitResult::Code(0)) {
        return Err(LearnError::Usage(format!(
            "verification_script failed for eval {}, {} run {}",
            req.eval.id,
            req.cfg.as_str(),
            req.run
        )));
    }

    let mut output = Vec::with_capacity(MAX_VERIFICATION_OUTPUT_BYTES);
    fs::File::open(&verification_path)
        .and_then(|file| {
            file.take(MAX_VERIFICATION_OUTPUT_BYTES as u64)
                .read_to_end(&mut output)
        })
        .map_err(|err| LearnError::Usage(format!("failed to read verification.json: {err}")))?;

    let invalid = || {
        LearnError::Usage(format!(
            "invalid verification result for eval {}, {} run {}",
            req.eval.id,
            req.cfg.as_str(),
            req.run
        ))
    };
    let value: Value = serde_json::from_slice(&output).map_err(|_| invalid())?;
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

fn forward_file_to_stderr(path: &Path) -> Result<(), LearnError> {
    let mut file = fs::File::open(path)
        .map_err(|err| LearnError::Usage(format!("failed to read verification stderr: {err}")))?;
    io::copy(&mut file, &mut io::stderr().lock())
        .map_err(|err| LearnError::Usage(format!("failed to write verification stderr: {err}")))?;
    Ok(())
}

fn kill_verification_process_group(pgid_path: &Path) -> io::Result<()> {
    let pgid: i32 = fs::read_to_string(pgid_path)?
        .trim()
        .parse()
        .map_err(|err| io::Error::other(format!("parse verification process group: {err}")))?;
    // SAFETY: pgid is written by this child immediately before it execs the
    // verification script, and the direct child has exited or timed out.
    if unsafe { libc::killpg(pgid, libc::SIGKILL) } == -1 {
        let err = io::Error::last_os_error();
        if err.raw_os_error() != Some(libc::ESRCH) {
            return Err(err);
        }
    }
    Ok(())
}

/// Streams script stdout to its artifact without retaining it in memory.
/// Once one byte beyond the artifact limit arrives, kill the script's whole
/// process group and continue draining until the pipe closes.
fn capture_verification_output(
    fifo_path: &Path,
    output_path: &Path,
    pgid_path: &Path,
) -> io::Result<bool> {
    let mut input = fs::File::open(fifo_path)?;
    let mut output = fs::File::create(output_path)?;
    let mut buffer = [0; 64 * 1024];
    let mut written = 0usize;
    let mut exceeded_limit = false;

    loop {
        let read = input.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        if exceeded_limit {
            continue;
        }

        let keep = read.min(MAX_VERIFICATION_OUTPUT_BYTES - written);
        output.write_all(&buffer[..keep])?;
        written += keep;
        if keep < read {
            exceeded_limit = true;
            kill_verification_process_group(pgid_path)?;
        }
    }

    output.flush()?;
    Ok(exceeded_limit)
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
