//! `eval output`: run a skill's output-quality eval set with and without the
//! skill, writing the same per-run artifacts as `skills/eval-tools/run-output-evals.sh`.
//!
//! Ports the runner's input validation, sandboxing, with/without-skill
//! `claude` invocations, deterministic `verification_script` grading, the
//! LLM judge, and `benchmark.json` aggregation.

mod adapter;
mod grade;
mod run;

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

use crate::error::LearnError;
pub use run::RunRecord;
use run::{ExecuteRunArgs, execute_run};

/// Which side of the with/without-skill comparison a run belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Config {
    WithSkill,
    WithoutSkill,
}

impl Config {
    /// Directory-name form, matching the shell runner's `$cfg`.
    pub fn as_str(self) -> &'static str {
        match self {
            Config::WithSkill => "with_skill",
            Config::WithoutSkill => "without_skill",
        }
    }
}

/// How an evaluated `claude` run ended, persisted in `timing.json`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EvalOutcome {
    Completed,
    Failed,
    TimedOut,
}

impl EvalOutcome {
    pub fn as_str(self) -> &'static str {
        match self {
            EvalOutcome::Completed => "completed",
            EvalOutcome::Failed => "failed",
            EvalOutcome::TimedOut => "timed_out",
        }
    }
}

/// Inputs to an `eval output` run, mirroring the CLI flags of
/// `skills/eval-tools/run-output-evals.sh`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutputHarness {
    Codex,
    Claude,
}
impl OutputHarness {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Codex => "codex",
            Self::Claude => "claude",
        }
    }
    pub fn default_model(self) -> Option<&'static str> {
        match self {
            Self::Codex => Some("gpt-6-luna"),
            Self::Claude => None,
        }
    }
}

pub struct OutputRequest {
    pub harness: OutputHarness,
    pub model: Option<String>,
    pub judge_model: Option<String>,
    pub skill_dir: PathBuf,
    pub runs: u32,
    pub iteration: u32,
    pub workspace: Option<PathBuf>,
    pub eval_ids: Vec<String>,
    pub timeout_seconds: u64,
    pub sandbox_dir: Option<PathBuf>,
    pub no_baseline: bool,
}

/// Result of an `eval output` run: every run's outcome, in execution order,
/// plus the aggregated `benchmark.json` this run wrote.
pub struct OutputReport {
    pub iteration_dir: PathBuf,
    pub records: Vec<RunRecord>,
    pub benchmark: Value,
}

/// One eval case from `evals/evals.json`.
struct EvalCase {
    id: String,
    prompt: String,
    expected_output: String,
    files: Vec<String>,
    env: Vec<(String, String)>,
    assertions: Vec<String>,
    setup_script: Option<String>,
    verification_script: Option<String>,
}

/// Run every selected eval x config x run, validating inputs up front.
pub fn run_output(req: &OutputRequest) -> Result<OutputReport, LearnError> {
    let (skill_dir, evals) = validate_output_request(req)?;
    let workspace = req.workspace.clone().unwrap_or_else(|| {
        let mut name = skill_dir.clone().into_os_string();
        name.push("-workspace");
        PathBuf::from(name)
    });
    let iteration_dir = workspace.join(format!("iteration-{}", req.iteration));
    fs::create_dir_all(&iteration_dir).map_err(|err| {
        LearnError::Usage(format!(
            "failed to create workspace {}: {err}",
            iteration_dir.display()
        ))
    })?;

    let records = execute_selected_evals(req, &skill_dir, &evals, &iteration_dir)?;
    let benchmark = write_benchmark(req, &skill_dir, &records, &iteration_dir)?;

    Ok(OutputReport {
        iteration_dir,
        records,
        benchmark,
    })
}

fn validate_output_request(req: &OutputRequest) -> Result<(PathBuf, Vec<EvalCase>), LearnError> {
    if req.runs == 0 {
        return Err(LearnError::Usage(
            "--runs must be a positive integer".to_string(),
        ));
    }
    if req.timeout_seconds == 0 {
        return Err(LearnError::Usage(
            "--timeout-seconds must be a positive integer".to_string(),
        ));
    }
    if !cli_available(req.harness.as_str()) {
        return Err(LearnError::Usage(format!(
            "{} CLI is required",
            req.harness.as_str()
        )));
    }
    if !req.skill_dir.is_dir() {
        return Err(LearnError::Usage(format!(
            "skill dir not found: {}",
            req.skill_dir.display()
        )));
    }
    let skill_dir = fs::canonicalize(&req.skill_dir).map_err(|err| {
        LearnError::Usage(format!(
            "skill dir not found: {}: {err}",
            req.skill_dir.display()
        ))
    })?;
    if !skill_dir.join("SKILL.md").is_file() {
        return Err(LearnError::Usage(format!(
            "no SKILL.md in {}",
            skill_dir.display()
        )));
    }
    if let Some(sandbox_dir) = &req.sandbox_dir {
        if !sandbox_dir.is_dir() {
            return Err(LearnError::Usage(format!(
                "sandbox dir not found: {}",
                sandbox_dir.display()
            )));
        }
        if sandbox_dir.join(".git").is_file() {
            return Err(LearnError::Usage(
                "--sandbox-dir must be a standalone clone or directory, not a linked worktree"
                    .to_string(),
            ));
        }
    }

    let evals = load_evals(&skill_dir)?;
    for wanted in &req.eval_ids {
        if !evals.iter().any(|eval| &eval.id == wanted) {
            return Err(LearnError::Usage(format!("evaluation not found: {wanted}")));
        }
    }
    Ok((skill_dir, evals))
}

fn execute_selected_evals(
    req: &OutputRequest,
    skill_dir: &Path,
    evals: &[EvalCase],
    iteration_dir: &Path,
) -> Result<Vec<RunRecord>, LearnError> {
    let configs: &[Config] = if req.no_baseline {
        &[Config::WithSkill]
    } else {
        &[Config::WithSkill, Config::WithoutSkill]
    };

    let mut records = Vec::new();
    for eval in evals {
        if !req.eval_ids.is_empty() && !req.eval_ids.iter().any(|id| id == &eval.id) {
            continue;
        }
        validate_skill_file(
            skill_dir,
            eval.setup_script.as_deref(),
            "setup_script not found",
        )?;
        validate_skill_file(
            skill_dir,
            eval.verification_script.as_deref(),
            "verification_script not found",
        )?;
        for file in &eval.files {
            validate_skill_file(
                skill_dir,
                Some(file.as_str()),
                &format!("input file not found for eval {}", eval.id),
            )?;
        }

        let eval_dir = iteration_dir.join(format!("eval-{}", eval.id));
        for &cfg in configs {
            for run in 1..=req.runs {
                let record = execute_run(ExecuteRunArgs {
                    skill_dir,
                    eval,
                    cfg,
                    run,
                    eval_dir: &eval_dir,
                    sandbox_template: req.sandbox_dir.as_deref(),
                    timeout_seconds: req.timeout_seconds,
                    options: req,
                })?;
                records.push(record);
            }
        }
    }
    Ok(records)
}

fn write_benchmark(
    req: &OutputRequest,
    skill_dir: &Path,
    records: &[RunRecord],
    iteration_dir: &Path,
) -> Result<Value, LearnError> {
    let mut benchmark = build_benchmark(skill_dir, req.iteration, records);
    benchmark["harness"] = json!(req.harness.as_str());
    benchmark["model"] = json!(req.model.as_deref().or(req.harness.default_model()));
    benchmark["judge_model"] = json!(
        req.judge_model
            .as_deref()
            .or(req.model.as_deref())
            .or(req.harness.default_model())
    );
    fs::write(
        iteration_dir.join("benchmark.json"),
        serde_json::to_vec_pretty(&benchmark)
            .map_err(|err| LearnError::Usage(format!("failed to encode benchmark.json: {err}")))?,
    )
    .map_err(|err| LearnError::Usage(format!("failed to write benchmark.json: {err}")))?;

    Ok(benchmark)
}

/// Ports the `agg()`/delta jq pipeline at the tail of
/// `run-output-evals.sh`: per-config pass rate, token, cost, time, and
/// successful-assertion-efficiency aggregates, plus the with/without delta.
fn build_benchmark(skill_dir: &Path, iteration: u32, records: &[RunRecord]) -> Value {
    let with_skill = aggregate_config(records, Config::WithSkill);
    let without_skill = aggregate_config(records, Config::WithoutSkill);
    let delta = match (&with_skill, &without_skill) {
        (Value::Null, _) | (_, Value::Null) => Value::Null,
        (with, without) => json!({
            "pass_rate": num(with, "pass_rate", "mean") - num(without, "pass_rate", "mean"),
            "tokens": delta_or_null(with, without, "tokens", "mean"),
            "cost_usd": delta_or_null(with, without, "cost_usd", "mean"),
            "time_seconds": num(with, "time_seconds", "mean") - num(without, "time_seconds", "mean"),
            "successful_assertions": num(with, "successful_assertions", "total")
                - num(without, "successful_assertions", "total"),
            "successful_assertions_per_1000_tokens": delta_or_null(
                with,
                without,
                "token_efficiency",
                "successful_assertions_per_1000_tokens",
            ),
        }),
    };
    json!({
        "skill": skill_dir.display().to_string(),
        "iteration": iteration,
        "run_summary": {
            "with_skill": with_skill,
            "without_skill": without_skill,
            "delta": delta,
        },
    })
}

fn num(value: &Value, section: &str, field: &str) -> f64 {
    value
        .get(section)
        .and_then(|v| v.get(field))
        .and_then(Value::as_f64)
        .unwrap_or(0.0)
}

fn delta_or_null(with: &Value, without: &Value, section: &str, field: &str) -> Value {
    match (
        with.get(section).and_then(|v| v.get(field)),
        without.get(section).and_then(|v| v.get(field)),
    ) {
        (Some(w), Some(o)) if w.is_number() && o.is_number() => {
            json!(round4(
                w.as_f64().unwrap_or(0.0) - o.as_f64().unwrap_or(0.0)
            ))
        }
        _ => Value::Null,
    }
}

fn round1(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}

fn round4(value: f64) -> f64 {
    (value * 10000.0).round() / 10000.0
}

/// Ports the shell `agg()` awk pipeline for one config's runs; `Value::Null`
/// when that config has no runs (mirrors `[ "$with" != null ]` gating the
/// delta).
fn aggregate_config(records: &[RunRecord], cfg: Config) -> Value {
    let runs: Vec<&RunRecord> = records.iter().filter(|r| r.config == cfg).collect();
    let n = runs.len();
    if n == 0 {
        return Value::Null;
    }

    let mut sum_rate = 0.0;
    let mut sum_rate_sq = 0.0;
    let mut sum_seconds = 0.0;
    let mut passed_total = 0u64;
    let mut completed = 0u32;
    let mut failed = 0u32;
    let mut timed_out = 0u32;
    let mut judge_timed_out = 0u32;
    let mut measured_runs = 0u64;
    let mut token_sum = 0u64;
    let mut measured_passed = 0u64;
    let mut costed_runs = 0u64;
    let mut cost_sum = 0.0;

    for run in &runs {
        let rate = if run.total_assertions > 0 {
            run.passed_assertions as f64 / run.total_assertions as f64
        } else {
            0.0
        };
        sum_rate += rate;
        sum_rate_sq += rate * rate;
        sum_seconds += (run.duration_ms / 1000) as f64;
        passed_total += run.passed_assertions as u64;
        match run.outcome {
            EvalOutcome::Completed => completed += 1,
            EvalOutcome::Failed => failed += 1,
            EvalOutcome::TimedOut => timed_out += 1,
        }
        if run.judge_outcome == "timed_out" {
            judge_timed_out += 1;
        }
        if let Some(tokens) = run.measured_tokens {
            measured_runs += 1;
            token_sum += tokens;
            measured_passed += run.passed_assertions as u64;
        }
        if let Some(cost) = run.cost_usd {
            costed_runs += 1;
            cost_sum += cost;
        }
    }

    let unavailable_runs = n as u64 - measured_runs;
    let mean_rate = sum_rate / n as f64;
    let variance = (sum_rate_sq / n as f64 - mean_rate * mean_rate).max(0.0);

    let (token_mean, token_total) = if measured_runs > 0 {
        (
            json!(round1(token_sum as f64 / measured_runs as f64)),
            json!(token_sum),
        )
    } else {
        (Value::Null, Value::Null)
    };
    let (cost_mean, cost_total) = if costed_runs > 0 {
        (
            json!(round4(cost_sum / costed_runs as f64)),
            json!(round4(cost_sum)),
        )
    } else {
        (Value::Null, Value::Null)
    };
    let (efficiency_status, efficiency) = if measured_runs == 0 {
        ("unavailable", Value::Null)
    } else if token_sum == 0 {
        ("zero_tokens", Value::Null)
    } else {
        let status = if unavailable_runs > 0 {
            "partial"
        } else {
            "measured"
        };
        (
            status,
            json!(round4(measured_passed as f64 * 1000.0 / token_sum as f64)),
        )
    };

    json!({
        "pass_rate": {"mean": round4(mean_rate), "stddev": round4(variance.sqrt())},
        "tokens": {
            "mean": token_mean, "total": token_total,
            "measured_runs": measured_runs, "unavailable_runs": unavailable_runs,
        },
        "cost_usd": {"mean": cost_mean, "total": cost_total, "measured_runs": costed_runs},
        "time_seconds": {"mean": round1(sum_seconds / n as f64)},
        "successful_assertions": {"total": passed_total},
        "token_efficiency": {
            "status": efficiency_status,
            "successful_assertions_per_1000_tokens": efficiency,
        },
        "outcomes": {
            "completed": completed, "failed": failed,
            "timed_out": timed_out, "judge_timed_out": judge_timed_out,
        },
        "runs": n,
    })
}

/// Ports `validate_skill_file()`: `rel` must stay inside `skill_dir` and
/// name an existing file. A missing/empty `rel` (unset script) is fine.
fn validate_skill_file(skill_dir: &Path, rel: Option<&str>, label: &str) -> Result<(), LearnError> {
    let Some(rel) = rel else {
        return Ok(());
    };
    if rel.is_empty() {
        return Ok(());
    }
    if escapes_skill_dir(rel) {
        return Err(LearnError::Usage(format!(
            "{label} must stay inside the skill directory: {rel}"
        )));
    }
    let full = skill_dir.join(rel);
    if !full.is_file() {
        return Err(LearnError::Usage(format!("{label}: {}", full.display())));
    }
    Ok(())
}

/// Ports the shell `case "$rel" in /*|..|../*|*/..|*/../*)` traversal guard.
fn escapes_skill_dir(rel: &str) -> bool {
    rel.starts_with('/')
        || rel == ".."
        || rel.starts_with("../")
        || rel.ends_with("/..")
        || rel.contains("/../")
}

fn load_evals(skill_dir: &Path) -> Result<Vec<EvalCase>, LearnError> {
    let path = skill_dir.join("evals/evals.json");
    if !path.is_file() {
        return Err(LearnError::Usage(format!(
            "no eval set at {}",
            path.display()
        )));
    }
    let text = fs::read_to_string(&path)
        .map_err(|err| LearnError::Usage(format!("no eval set at {}: {err}", path.display())))?;
    let value: Value = serde_json::from_str(&text)
        .map_err(|_| LearnError::Usage(format!("invalid JSON in {}", path.display())))?;
    let evals = value
        .get("evals")
        .and_then(Value::as_array)
        .ok_or_else(|| LearnError::Usage(format!("invalid JSON in {}", path.display())))?;
    if evals.is_empty() {
        return Err(LearnError::Usage(format!("no evals in {}", path.display())));
    }
    let evals: Vec<EvalCase> = evals
        .iter()
        .enumerate()
        .map(|(index, item)| parse_eval_case(item, index))
        .collect::<Result<_, _>>()?;
    let mut ids = HashSet::new();
    for eval in &evals {
        if !ids.insert(&eval.id) {
            return Err(LearnError::Usage(format!("duplicate eval id: {}", eval.id)));
        }
    }
    Ok(evals)
}

fn parse_eval_case(item: &Value, index: usize) -> Result<EvalCase, LearnError> {
    let id = match item.get("id") {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Number(n)) => n.to_string(),
        _ => (index + 1).to_string(),
    };
    if id.is_empty()
        || id == "."
        || id == ".."
        || id.contains(['/', '\\'])
        || id.chars().any(char::is_control)
    {
        return Err(LearnError::Usage(format!("invalid eval id: {id:?}")));
    }
    let prompt = item
        .get("prompt")
        .and_then(Value::as_str)
        .ok_or_else(|| LearnError::Usage(format!("eval {id} is missing a prompt")))?
        .to_string();
    let expected_output = item
        .get("expected_output")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let assertions = item
        .get("assertions")
        .and_then(Value::as_array)
        .map(|assertions| {
            assertions
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    let files = item
        .get("files")
        .and_then(Value::as_array)
        .map(|files| {
            files
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    let env = parse_case_env(item.get("env"), &id)?;
    let setup_script = item
        .get("setup_script")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let verification_script = item
        .get("verification_script")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    Ok(EvalCase {
        id,
        prompt,
        expected_output,
        files,
        env,
        assertions,
        setup_script,
        verification_script,
    })
}

fn parse_case_env(value: Option<&Value>, id: &str) -> Result<Vec<(String, String)>, LearnError> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    let invalid = || {
        LearnError::Usage(format!(
            "eval {id} env must be a string map with valid environment keys and no EVAL_* keys or NUL values"
        ))
    };
    let entries = value.as_object().ok_or_else(invalid)?;
    entries
        .iter()
        .map(|(key, value)| {
            let mut bytes = key.bytes();
            if !bytes
                .next()
                .is_some_and(|b| b.is_ascii_alphabetic() || b == b'_')
                || !bytes.all(|b| b.is_ascii_alphanumeric() || b == b'_')
                || key.starts_with("EVAL_")
            {
                return Err(invalid());
            }
            let value = value
                .as_str()
                .filter(|v| !v.contains('\0'))
                .ok_or_else(invalid)?;
            Ok((key.clone(), value.to_string()))
        })
        .collect()
}

/// `command -v <name>`, without shelling out, matching `crate::trigger`'s
/// dependency check.
fn cli_available(name: &str) -> bool {
    let Some(path_var) = std::env::var_os("PATH") else {
        return false;
    };
    std::env::split_paths(&path_var).any(|dir| is_executable_file(&dir.join(name)))
}

#[cfg(unix)]
fn is_executable_file(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    fs::metadata(path)
        .map(|meta| meta.is_file() && meta.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

#[cfg(not(unix))]
fn is_executable_file(path: &Path) -> bool {
    path.is_file()
}
