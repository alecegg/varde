//! One eval x config x run: fresh sandbox, optional skill snapshot and
//! `setup_script`, the `claude -p` invocation under a deadline, and the
//! per-run artifacts (`raw.json`, `transcript.txt`, `outputs/transcript.txt`,
//! `timing.json`, `setup.txt`).

use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::{Value, json};

use crate::error::LearnError;
use crate::{ExitResult, RunOutcome as ProcessOutcome, RunRequest, run_with_timeout};

use super::adapter;
use super::grade::{GradeRequest, grade_run};
use super::{Config, EvalCase, EvalOutcome, OutputHarness, OutputRequest};

/// Exit-code convention for a timed-out run, matching the shell runner's
/// `claude-timeout.pl` convention (`128 + SIGALRM`) used throughout
/// `skills/eval-tools/run-output-evals.sh` and its tests.
const TIMED_OUT_EXIT_CODE: i32 = 142;

/// One run's disk location, outcome, and grading summary — everything
/// `benchmark.json` aggregation needs.
pub struct RunRecord {
    pub eval_id: String,
    pub config: Config,
    pub run: u32,
    pub run_dir: PathBuf,
    pub outcome: EvalOutcome,
    pub judge_outcome: &'static str,
    pub total_assertions: u32,
    pub passed_assertions: u32,
    pub duration_ms: u64,
    pub measured_tokens: Option<u64>,
    pub cost_usd: Option<f64>,
}

pub(super) struct ExecuteRunArgs<'a> {
    pub(super) skill_dir: &'a Path,
    pub(super) eval: &'a EvalCase,
    pub(super) cfg: Config,
    pub(super) run: u32,
    pub(super) eval_dir: &'a Path,
    pub(super) sandbox_template: Option<&'a Path>,
    pub(super) timeout_seconds: u64,
    pub(super) options: &'a OutputRequest,
}

pub(super) fn execute_run(args: ExecuteRunArgs<'_>) -> Result<RunRecord, LearnError> {
    let ExecuteRunArgs {
        skill_dir,
        eval,
        cfg,
        run,
        eval_dir,
        sandbox_template,
        timeout_seconds,
        options,
    } = args;
    let eval_run_start = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);

    let run_dir = eval_dir.join(cfg.as_str()).join(format!("run-{run}"));
    fs::create_dir_all(run_dir.join("outputs")).map_err(|err| {
        LearnError::Usage(format!(
            "failed to create run dir {}: {err}",
            run_dir.display()
        ))
    })?;
    let run_dir_abs = fs::canonicalize(&run_dir).map_err(|err| {
        LearnError::Usage(format!(
            "failed to resolve run dir {}: {err}",
            run_dir.display()
        ))
    })?;

    // Every run gets a fresh sandbox outside HOME, never reused across runs.
    let sbox = tempfile::Builder::new()
        .prefix("varde-learn-output-sbox-")
        .tempdir()
        .map_err(|err| LearnError::Usage(format!("failed to create sandbox: {err}")))?;
    let sbox_root = fs::canonicalize(sbox.path())
        .map_err(|err| LearnError::Usage(format!("failed to resolve sandbox: {err}")))?;
    let sbox_path = sbox_root.as_path();
    let case_env: Vec<_> = eval
        .env
        .iter()
        .map(|(key, value)| {
            (
                key.clone(),
                value.replace("{sandbox}", &sbox_path.to_string_lossy()),
            )
        })
        .collect();
    if let Some(template) = sandbox_template {
        copy_dir_contents(template, sbox_path)
            .map_err(|err| LearnError::Usage(format!("failed to seed sandbox: {err}")))?;
    }

    let skill_sbox = if cfg == Config::WithSkill {
        let target = sbox_path.join(".skill-under-evaluation");
        copy_dir_contents(skill_dir, &target)
            .map_err(|err| LearnError::Usage(format!("failed to copy skill snapshot: {err}")))?;
        // Match the installer: keep eval prompts, answers, and helper
        // scripts runner-side, not visible to the evaluated agent.
        let _ = fs::remove_dir_all(target.join("evals"));
        Some(target)
    } else {
        None
    };

    for file in &eval.files {
        let dest = sbox_path.join(file);
        if let Some(parent) = dest.parent() {
            fs::create_dir_all(parent).map_err(|err| {
                LearnError::Usage(format!("failed to seed input file {file}: {err}"))
            })?;
        }
        fs::copy(skill_dir.join(file), &dest)
            .map_err(|err| LearnError::Usage(format!("failed to seed input file {file}: {err}")))?;
    }

    if let Some(setup_script) = &eval.setup_script {
        run_setup_script(&SetupScriptRequest {
            skill_dir,
            script_rel: setup_script,
            sbox: sbox_path,
            run_dir: &run_dir,
            run_dir_abs: &run_dir_abs,
            env: &case_env,
            eval_id: &eval.id,
            cfg,
            run,
            timeout_seconds,
        })?;
    }

    let prompt = match &skill_sbox {
        Some(skill_sbox) => format!(
            "Evaluate only the skill snapshot at {sbox}/SKILL.md.\n\
             Read it directly. Resolve every relative path from {sbox}.\n\
             Do not invoke or read an installed skill sharing its name.\n\
             Then handle this request:\n\n{prompt}",
            sbox = skill_sbox.display(),
            prompt = eval.prompt,
        ),
        None => eval.prompt.clone(),
    };

    let mut args = adapter::args(
        options.harness,
        options.model.as_deref(),
        &prompt,
        sbox_path,
        false,
    );
    if options.harness == OutputHarness::Claude {
        args.extend(["--permission-mode".into(), "auto".into()]);
        if let Some(skill_sbox) = &skill_sbox {
            args.extend(["--add-dir".into(), skill_sbox.display().to_string()]);
        }
    }

    let raw_path = run_dir.join("raw.json");
    let stream_path = if options.harness == OutputHarness::Codex {
        run_dir.join("raw.jsonl")
    } else {
        raw_path.clone()
    };
    let stderr_path = run_dir.join("raw.stderr.log");
    let start = Instant::now();
    let request = RunRequest {
        program: options.harness.as_str(),
        args: &args,
        cwd: Some(sbox_path),
        env: &case_env,
        stdin: if options.harness == OutputHarness::Codex {
            prompt.as_bytes()
        } else {
            &[]
        },
        stdout_path: &stream_path,
        stderr_path: &stderr_path,
        timeout: Duration::from_secs(timeout_seconds),
    };
    let process_outcome = run_with_timeout(&request)?;
    let elapsed_ms = start.elapsed().as_millis() as u64;

    let (mut outcome, exit_code) = match process_outcome {
        ProcessOutcome::Completed(ExitResult::Code(0)) => (EvalOutcome::Completed, 0),
        ProcessOutcome::Completed(other) => (EvalOutcome::Failed, other.as_shell_code()),
        ProcessOutcome::TimedOut => (EvalOutcome::TimedOut, TIMED_OUT_EXIT_CODE),
    };

    let (raw_value, trace_error) = adapter::read_raw(options.harness, &stream_path, &raw_path)?;
    if trace_error.is_some() && outcome == EvalOutcome::Completed {
        outcome = EvalOutcome::Failed;
    }

    let transcript = raw_value
        .as_ref()
        .map(extract_transcript)
        .unwrap_or_default();
    fs::write(run_dir.join("outputs").join("transcript.txt"), &transcript)
        .map_err(|err| LearnError::Usage(format!("failed to write transcript: {err}")))?;
    fs::write(run_dir.join("transcript.txt"), &transcript)
        .map_err(|err| LearnError::Usage(format!("failed to write transcript: {err}")))?;

    let (measured, tokens) = raw_value.as_ref().map(extract_tokens).unwrap_or((false, 0));
    let duration_ms = raw_value
        .as_ref()
        .and_then(|value| value.get("duration_ms").and_then(Value::as_u64))
        .unwrap_or(elapsed_ms);
    let measured_tokens = measured.then_some(tokens);
    let cost_usd = raw_value
        .as_ref()
        .and_then(|value| value.get("total_cost_usd").and_then(Value::as_f64));
    let timing = json!({
        "harness": options.harness.as_str(),
        "model": options.model.as_deref().or(options.harness.default_model()),
        "trace_error": trace_error,
        "duration_ms": duration_ms,
        "tokens": measured_tokens,
        "outcome": outcome.as_str(),
        "exit_code": exit_code,
        "timeout_seconds": timeout_seconds,
    });
    fs::write(
        run_dir.join("timing.json"),
        serde_json::to_vec_pretty(&timing)
            .map_err(|err| LearnError::Usage(format!("failed to encode timing.json: {err}")))?,
    )
    .map_err(|err| LearnError::Usage(format!("failed to write timing.json: {err}")))?;

    let summary = grade_run(&GradeRequest {
        env: &case_env,
        skill_dir,
        eval,
        cfg,
        run,
        eval_run_start,
        run_dir: &run_dir,
        run_dir_abs: &run_dir_abs,
        sbox: sbox_path,
        raw_path: &raw_path,
        transcript: &transcript,
        run_outcome: outcome,
        timeout_seconds,
        harness: options.harness,
        model: options.judge_model.as_deref().or(options.model.as_deref()),
    })?;

    Ok(RunRecord {
        eval_id: eval.id.clone(),
        config: cfg,
        run,
        run_dir,
        outcome,
        judge_outcome: summary.judge_outcome,
        total_assertions: summary.total,
        passed_assertions: summary.passed,
        duration_ms,
        measured_tokens,
        cost_usd,
    })
}

/// Inputs to [`run_setup_script`], bundled to avoid an eight-argument
/// signature (mirrors [`crate::process::RunRequest`]'s request-struct style).
struct SetupScriptRequest<'a> {
    env: &'a [(String, String)],
    skill_dir: &'a Path,
    script_rel: &'a str,
    sbox: &'a Path,
    run_dir: &'a Path,
    run_dir_abs: &'a Path,
    eval_id: &'a str,
    cfg: Config,
    run: u32,
    timeout_seconds: u64,
}

fn run_setup_script(req: &SetupScriptRequest) -> Result<(), LearnError> {
    let script_path = req.skill_dir.join(req.script_rel);
    let stdout_path = req.run_dir.join("setup.txt");
    let stderr_path = req.run_dir.join("setup.stderr.tmp");
    // Keep setup.txt's historical combined output while letting the shared
    // process runner manage the deadline and the whole child process group.
    let args = vec![
        "-c".to_string(),
        "exec 2>&1; exec bash \"$0\"".to_string(),
        script_path.display().to_string(),
    ];
    let mut env = req.env.to_vec();
    env.extend([
        ("EVAL_ID".to_string(), req.eval_id.to_string()),
        ("EVAL_CONFIG".to_string(), req.cfg.as_str().to_string()),
        ("EVAL_RUN".to_string(), req.run.to_string()),
        (
            "EVAL_RUN_DIR".to_string(),
            req.run_dir_abs.display().to_string(),
        ),
        (
            "EVAL_SKILL_DIR".to_string(),
            req.skill_dir.display().to_string(),
        ),
        (
            "EVAL_SANDBOX_DIR".to_string(),
            req.sbox.display().to_string(),
        ),
    ]);
    let request = RunRequest {
        program: "bash",
        args: &args,
        cwd: Some(req.sbox),
        env: &env,
        stdin: &[],
        stdout_path: &stdout_path,
        stderr_path: &stderr_path,
        timeout: Duration::from_secs(req.timeout_seconds),
    };
    let outcome = run_with_timeout(&request);
    let append_result = append_file(&stderr_path, &stdout_path);
    let _ = fs::remove_file(&stderr_path);
    append_result?;

    match outcome? {
        ProcessOutcome::Completed(ExitResult::Code(0)) => Ok(()),
        ProcessOutcome::TimedOut => Err(LearnError::Usage(format!(
            "setup_script timed out after {} seconds for eval {}, {} run {}",
            req.timeout_seconds,
            req.eval_id,
            req.cfg.as_str(),
            req.run
        ))),
        ProcessOutcome::Completed(_) => Err(LearnError::Usage(format!(
            "setup_script failed for eval {}, {} run {}",
            req.eval_id,
            req.cfg.as_str(),
            req.run
        ))),
    }
}

fn append_file(source: &Path, destination: &Path) -> Result<(), LearnError> {
    let mut source = fs::File::open(source)
        .map_err(|err| LearnError::Usage(format!("failed to read setup stderr: {err}")))?;
    let mut destination = fs::OpenOptions::new()
        .append(true)
        .open(destination)
        .map_err(|err| LearnError::Usage(format!("failed to append setup stderr: {err}")))?;
    io::copy(&mut source, &mut destination)
        .map_err(|err| LearnError::Usage(format!("failed to append setup stderr: {err}")))?;
    Ok(())
}

/// Recursively copies the *contents* of `src` into `dst` (which may already
/// exist), matching `cp -R "$src"/. "$dst"/`. Symlinks are recreated as
/// symlinks rather than followed, matching `cp -R`'s BSD/macOS behavior.
fn copy_dir_contents(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let target = dst.join(entry.file_name());
        let file_type = entry.file_type()?;
        if file_type.is_symlink() {
            let link_target = fs::read_link(entry.path())?;
            std::os::unix::fs::symlink(link_target, &target)?;
        } else if file_type.is_dir() {
            copy_dir_contents(&entry.path(), &target)?;
        } else {
            fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

/// Ports `extract_text()`: the run's `.result` field, or its streamed text
/// message parts joined by newlines. Shared with `grade.rs`, which applies
/// the same extraction to the judge's envelope.
pub(super) fn extract_transcript(value: &Value) -> String {
    if let Some(result) = value.get("result").and_then(Value::as_str) {
        return result.to_string();
    }
    value
        .get("messages")
        .and_then(Value::as_array)
        .map(|messages| {
            messages
                .iter()
                .filter_map(|message| message.get("content").and_then(Value::as_array))
                .flatten()
                .filter(|part| part.get("type").and_then(Value::as_str) == Some("text"))
                .filter_map(|part| part.get("text").and_then(Value::as_str))
                .collect::<Vec<_>>()
                .join("\n")
        })
        .unwrap_or_default()
}

/// Whether `.usage` reported any numeric token field, and the sum of
/// whichever fields are numbers (non-numeric fields count as zero),
/// mirroring `record_run_timing()`'s `token_status`/token sum jq filters.
fn extract_tokens(value: &Value) -> (bool, u64) {
    const FIELDS: [&str; 4] = [
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ];
    let Some(usage) = value.get("usage").and_then(Value::as_object) else {
        return (false, 0);
    };
    let mut measured = false;
    let mut sum = 0u64;
    for field in FIELDS {
        if let Some(n) = usage.get(field).and_then(Value::as_u64) {
            measured = true;
            sum += n;
        }
    }
    (measured, sum)
}
