//! Run agent-authored JavaScript over a capture inside an embedded QuickJS realm.
//!
//! QuickJS has no direct filesystem, network, process, or module access. The CLI installs a
//! command binding; captured tool output is read through `LineSource`.

use anyhow::Result;
use rquickjs::function::{Opt, Rest};
use rquickjs::{
    CatchResultExt, CaughtError, Context, Ctx, FromJs, Function, Object, Runtime, Value,
};
use std::cell::RefCell;
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

/// Bounds enforced by the engine. Every one is also a config knob on the CLI.
#[derive(Debug, Clone)]
pub struct Limits {
    pub timeout_ms: u64,
    pub memory_bytes: usize,
    pub max_output_bytes: usize,
    pub max_text_bytes: usize,
    pub max_stack_bytes: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            timeout_ms: 5_000,
            memory_bytes: 64 * 1024 * 1024,
            max_output_bytes: 1024 * 1024,
            max_text_bytes: 16 * 1024 * 1024,
            max_stack_bytes: 1024 * 1024,
        }
    }
}

/// What the script sees as `toz.handle`.
#[derive(Debug, Clone, Default)]
pub struct Meta {
    pub handle: String,
    pub label: String,
    pub bytes: i64,
    pub lines: i64,
    pub exit_code: Option<i32>,
    /// Stream used when the script does not name one; mirrors `--stream`.
    pub stream: String,
}

/// Exit codes skip 2: `main.rs` maps every `Err` to 2, so reusing it here would make "the script
/// timed out" indistinguishable from "toz could not open the store".
#[derive(Debug)]
pub enum Outcome {
    Ok(String),
    Exception(String),
    Timeout,
    MemoryLimit,
    OutputLimit,
}

impl Outcome {
    pub fn exit_code(&self) -> i32 {
        match self {
            Outcome::Ok(_) => 0,
            Outcome::Exception(_) => 1,
            Outcome::Timeout => 3,
            Outcome::MemoryLimit => 4,
            Outcome::OutputLimit => 5,
        }
    }
}

/// Where capture text comes from. A trait so the engine does not depend on `Store`, and so tests
/// can drive it from a vector.
pub trait LineSource {
    fn for_each_line(&self, stream: &str, f: &mut dyn FnMut(&str) -> Result<()>) -> Result<()>;
}

/// An empty input for scripts that do not operate on a capture.
pub struct EmptyLines;

/// Host command execution available to a script. The CLI supplies the existing command runner.
pub trait CommandCaller {
    fn exec(&self, request: serde_json::Value, timeout: Duration) -> Result<serde_json::Value>;
}

impl LineSource for EmptyLines {
    fn for_each_line(&self, _stream: &str, _f: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
        Ok(())
    }
}

/// Short stable fingerprint of a script, used to build the capture's supersession key so that
/// re-running the same script replaces its own prior result while a different script does not.
pub fn source_fingerprint(source: &str) -> String {
    crate::content_hash(source.as_bytes())[..12].to_string()
}

/// `LineSource` over text already in memory, for running a profile's script against a fresh
/// capture before it round-trips through the store.
pub struct TextLines {
    stdout: Vec<String>,
    stderr: Vec<String>,
}

impl TextLines {
    pub fn new(stdout_text: &str, stderr_text: &str) -> Self {
        Self {
            stdout: stdout_text.lines().map(str::to_string).collect(),
            stderr: stderr_text.lines().map(str::to_string).collect(),
        }
    }
}

impl LineSource for TextLines {
    fn for_each_line(&self, stream: &str, f: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
        let lines = if stream == "stderr" {
            &self.stderr
        } else {
            &self.stdout
        };
        for l in lines {
            f(l)?;
        }
        Ok(())
    }
}

/// One `toz.record(kind, obj)` call, in call order.
#[derive(Debug, Clone)]
pub struct Record {
    pub kind: String,
    pub json: String,
}

/// `LineSource` backed by a capture in the store.
pub struct StoreLines {
    store: crate::Store,
    capture_id: i64,
}

impl StoreLines {
    pub fn new(store: crate::Store, capture_id: i64) -> Self {
        Self { store, capture_id }
    }
}

impl LineSource for StoreLines {
    fn for_each_line(&self, stream: &str, f: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
        self.store.for_each_line(self.capture_id, stream, f)
    }
}

struct OutBuf {
    text: String,
    cap: usize,
    over: bool,
}

pub fn run(
    source: &str,
    meta: &Meta,
    src: Rc<dyn LineSource>,
    limits: &Limits,
) -> Result<(Outcome, Vec<Record>)> {
    run_with_tools(source, meta, src, limits, None)
}

pub fn run_with_tools(
    source: &str,
    meta: &Meta,
    src: Rc<dyn LineSource>,
    limits: &Limits,
    commands: Option<Rc<dyn CommandCaller>>,
) -> Result<(Outcome, Vec<Record>)> {
    let rt = Runtime::new()?;
    rt.set_memory_limit(limits.memory_bytes);
    rt.set_max_stack_size(limits.max_stack_bytes);

    // The interrupt handler is the only way out of a runaway loop; QuickJS calls it between
    // operations and a `true` return unwinds with an uncatchable error.
    let deadline = Instant::now() + Duration::from_millis(limits.timeout_ms);
    let timed_out = Arc::new(AtomicBool::new(false));
    {
        let flag = timed_out.clone();
        rt.set_interrupt_handler(Some(Box::new(move || {
            if Instant::now() >= deadline {
                flag.store(true, Ordering::SeqCst);
                true
            } else {
                false
            }
        })));
    }

    let ctx = Context::full(&rt)?;
    let out = Rc::new(RefCell::new(OutBuf {
        text: String::new(),
        cap: limits.max_output_bytes,
        over: false,
    }));
    let records = Rc::new(RefCell::new(Vec::<Record>::new()));

    let result = ctx.with(|ctx| {
        evaluate_script(
            ctx,
            source,
            meta,
            src,
            limits,
            commands,
            deadline,
            timed_out,
            out,
            records.clone(),
        )
    })?;

    let collected = records.borrow().clone();
    Ok((result, collected))
}

#[allow(clippy::too_many_arguments)]
fn evaluate_script<'js>(
    ctx: Ctx<'js>,
    source: &str,
    meta: &Meta,
    src: Rc<dyn LineSource>,
    limits: &Limits,
    commands: Option<Rc<dyn CommandCaller>>,
    deadline: Instant,
    timed_out: Arc<AtomicBool>,
    out: Rc<RefCell<OutBuf>>,
    records: Rc<RefCell<Vec<Record>>>,
) -> Result<Outcome> {
    let globals = ctx.globals();
    install_print(&ctx, &globals, out.clone())?;
    install_toz(
        &ctx, &globals, meta, src, limits, commands, deadline, records,
    )?;
    match ctx.eval::<Value, _>(source).catch(&ctx) {
        Ok(_) => {
            if Instant::now() >= deadline {
                return Ok(Outcome::Timeout);
            }
            let b = out.borrow();
            if b.over {
                Ok(Outcome::OutputLimit)
            } else {
                Ok(Outcome::Ok(b.text.clone()))
            }
        }
        Err(caught) => {
            if timed_out.load(Ordering::SeqCst) || Instant::now() >= deadline {
                return Ok(Outcome::Timeout);
            }
            if out.borrow().over {
                return Ok(Outcome::OutputLimit);
            }
            Ok(classify(caught))
        }
    }
}

/// Hitting the memory limit does not surface as a normal exception: QuickJS cannot allocate an
/// `Error` object to throw, so the pending exception value is null. That null is the signal.
fn classify(caught: CaughtError<'_>) -> Outcome {
    match caught {
        CaughtError::Error(rquickjs::Error::Allocation) => Outcome::MemoryLimit,
        CaughtError::Value(v) if v.is_null() || v.is_undefined() => Outcome::MemoryLimit,
        CaughtError::Exception(e) => {
            let msg = e.message().unwrap_or_else(|| "error".into());
            // The first stack frame carries the line number, which is what makes the message
            // actionable enough for the agent to revise the script rather than re-run it.
            match e.stack().and_then(|s| s.lines().next().map(str::to_string)) {
                Some(frame) if !frame.trim().is_empty() => {
                    Outcome::Exception(format!("{msg}  {}", frame.trim()))
                }
                _ => Outcome::Exception(msg),
            }
        }
        other => Outcome::Exception(other.to_string()),
    }
}

fn install_print<'js>(
    ctx: &Ctx<'js>,
    globals: &Object<'js>,
    out: Rc<RefCell<OutBuf>>,
) -> Result<()> {
    let write = move |ctx: Ctx<'js>, args: Rest<Value<'js>>| -> rquickjs::Result<()> {
        let mut parts: Vec<String> = Vec::with_capacity(args.len());
        for v in args.iter() {
            parts.push(stringify(&ctx, v)?);
        }
        let mut b = out.borrow_mut();
        if b.over {
            return Err(
                ctx.throw(rquickjs::String::from_str(ctx.clone(), "output limit exceeded")?.into())
            );
        }
        let line = parts.join(" ");
        if b.text.len() + line.len() + 1 > b.cap {
            b.over = true;
            return Err(
                ctx.throw(rquickjs::String::from_str(ctx.clone(), "output limit exceeded")?.into())
            );
        }
        b.text.push_str(&line);
        b.text.push('\n');
        Ok(())
    };
    let f = Function::new(ctx.clone(), write)?;
    globals.set("print", f.clone())?;
    let console = Object::new(ctx.clone())?;
    console.set("log", f.clone())?;
    console.set("error", f)?;
    globals.set("console", console)?;
    Ok(())
}

/// Objects and arrays are far more useful printed as JSON than as "[object Object]".
fn stringify<'js>(ctx: &Ctx<'js>, v: &Value<'js>) -> rquickjs::Result<String> {
    if v.is_object() && !v.is_function() {
        if let Ok(Some(s)) = ctx.json_stringify(v.clone()) {
            return s.to_string();
        }
    }
    rquickjs::Coerced::<String>::from_js(ctx, v.clone()).map(|c| c.0)
}

#[allow(clippy::too_many_arguments)]
fn install_toz<'js>(
    ctx: &Ctx<'js>,
    globals: &Object<'js>,
    meta: &Meta,
    src: Rc<dyn LineSource>,
    limits: &Limits,
    commands: Option<Rc<dyn CommandCaller>>,
    deadline: Instant,
    records: Rc<RefCell<Vec<Record>>>,
) -> Result<()> {
    let toz = Object::new(ctx.clone())?;

    let handle = Object::new(ctx.clone())?;
    handle.set("handle", meta.handle.as_str())?;
    handle.set("label", meta.label.as_str())?;
    handle.set("bytes", meta.bytes)?;
    handle.set("lines", meta.lines)?;
    match meta.exit_code {
        Some(c) => handle.set("exitCode", c)?,
        None => handle.set("exitCode", Value::new_null(ctx.clone()))?,
    }
    handle.set("stream", meta.stream.as_str())?;
    toz.set("handle", handle)?;

    let default_stream = meta.stream.clone();

    install_each_line(ctx, &toz, src.clone(), default_stream.clone())?;

    install_text(ctx, &toz, src, limits.max_text_bytes, default_stream)?;
    install_record(ctx, &toz, records)?;
    install_exec(ctx, &toz, commands, deadline)?;

    globals.set("vardeToz", toz.clone())?;
    globals.set("toz", toz)?;
    Ok(())
}

fn install_each_line<'js>(
    ctx: &Ctx<'js>,
    toz: &Object<'js>,
    src: Rc<dyn LineSource>,
    default_stream: String,
) -> Result<()> {
    // eachLine(fn) | eachLine(stream, fn)
    {
        let each =
            move |ctx: Ctx<'js>, a: Value<'js>, b: Opt<Value<'js>>| -> rquickjs::Result<()> {
                let (stream, cb) = match b.0 {
                    Some(second) => (rquickjs::Coerced::<String>::from_js(&ctx, a)?.0, second),
                    None => (default_stream.clone(), a),
                };
                let cb = cb.into_function().ok_or_else(|| {
                    ctx.throw(
                        rquickjs::String::from_str(ctx.clone(), "eachLine: expected a function")
                            .unwrap()
                            .into(),
                    )
                })?;
                // A JS throw inside the callback must surface as that same exception, not as a generic
                // host error, so it is carried out of the iteration rather than stringified.
                let mut js_err: Option<rquickjs::Error> = None;
                let walk = src.for_each_line(&stream, &mut |line| {
                    if js_err.is_some() {
                        return Err(anyhow::anyhow!("callback failed"));
                    }
                    match cb.call::<_, ()>((line,)) {
                        Ok(()) => Ok(()),
                        Err(e) => {
                            js_err = Some(e);
                            Err(anyhow::anyhow!("callback failed"))
                        }
                    }
                });
                if let Some(e) = js_err {
                    return Err(e);
                }
                walk.map_err(|e| {
                    ctx.throw(
                        rquickjs::String::from_str(ctx.clone(), &format!("eachLine: {e}"))
                            .unwrap()
                            .into(),
                    )
                })?;
                Ok(())
            };
        toz.set("eachLine", Function::new(ctx.clone(), each)?)?;
    }

    Ok(())
}

fn install_text<'js>(
    ctx: &Ctx<'js>,
    toz: &Object<'js>,
    src: Rc<dyn LineSource>,
    max: usize,
    default_stream: String,
) -> Result<()> {
    // text() | text(stream)
    {
        let text =
            move |ctx: Ctx<'js>, s: Opt<rquickjs::Coerced<String>>| -> rquickjs::Result<String> {
                let stream = s.0.map(|c| c.0).unwrap_or_else(|| default_stream.clone());
                let mut buf = String::new();
                let mut over = false;
                let walk = src.for_each_line(&stream, &mut |line| {
                    if buf.len() + line.len() + 1 > max {
                        over = true;
                        return Err(anyhow::anyhow!("text limit"));
                    }
                    buf.push_str(line);
                    buf.push('\n');
                    Ok(())
                });
                if over {
                    return Err(ctx.throw(
                    rquickjs::String::from_str(
                        ctx.clone(),
                        "toz.text(): capture exceeds max_text_bytes; use toz.eachLine() instead",
                    )?
                    .into(),
                ));
                }
                walk.map_err(|e| {
                    ctx.throw(
                        rquickjs::String::from_str(ctx.clone(), &format!("text: {e}"))
                            .unwrap()
                            .into(),
                    )
                })?;
                Ok(buf)
            };
        toz.set("text", Function::new(ctx.clone(), text)?)?;
    }

    Ok(())
}

fn install_record<'js>(
    ctx: &Ctx<'js>,
    toz: &Object<'js>,
    records: Rc<RefCell<Vec<Record>>>,
) -> Result<()> {
    // record(kind, obj) — appended in call order; persisted per capture after the script exits.
    {
        let record_fn = move |ctx: Ctx<'js>,
                              kind: rquickjs::Coerced<String>,
                              obj: Value<'js>|
              -> rquickjs::Result<()> {
            let json = match ctx.json_stringify(obj)? {
                Some(s) => s.to_string()?,
                None => "null".to_string(),
            };
            records.borrow_mut().push(Record { kind: kind.0, json });
            Ok(())
        };
        toz.set("record", Function::new(ctx.clone(), record_fn)?)?;
    }

    Ok(())
}

fn install_exec<'js>(
    ctx: &Ctx<'js>,
    toz: &Object<'js>,
    commands: Option<Rc<dyn CommandCaller>>,
    deadline: Instant,
) -> Result<()> {
    if let Some(commands) = commands {
        let exec = move |ctx: Ctx<'js>, request: Value<'js>| -> rquickjs::Result<Value<'js>> {
            let Some(json) = ctx.json_stringify(request)? else {
                return Err(js_error(&ctx, "exec request must be an object"));
            };
            let request: serde_json::Value = serde_json::from_str(&json.to_string()?)
                .map_err(|e| js_error(&ctx, &format!("exec request: {e}")))?;
            let remaining = deadline.saturating_duration_since(Instant::now());
            let result = commands
                .exec(request, remaining)
                .map_err(|e| js_error(&ctx, &format!("exec: {e:#}")))?;
            ctx.json_parse(
                serde_json::to_string(&result).map_err(|e| js_error(&ctx, &e.to_string()))?,
            )
        };
        toz.set("exec", Function::new(ctx.clone(), exec)?)?;
    }

    Ok(())
}

fn js_error<'js>(ctx: &Ctx<'js>, message: &str) -> rquickjs::Error {
    match rquickjs::String::from_str(ctx.clone(), message) {
        Ok(text) => ctx.throw(text.into()),
        Err(error) => error,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct VecSource {
        stdout: Vec<String>,
        stderr: Vec<String>,
    }

    impl VecSource {
        fn stdout(lines: &[&str]) -> Rc<dyn LineSource> {
            Rc::new(VecSource {
                stdout: lines.iter().map(|s| s.to_string()).collect(),
                stderr: Vec::new(),
            })
        }
    }

    impl LineSource for VecSource {
        fn for_each_line(&self, stream: &str, f: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
            let lines = if stream == "stderr" {
                &self.stderr
            } else {
                &self.stdout
            };
            for l in lines {
                f(l)?;
            }
            Ok(())
        }
    }

    fn meta() -> Meta {
        Meta {
            handle: "a1b2".into(),
            label: "git log".into(),
            bytes: 42,
            lines: 3,
            exit_code: Some(0),
            stream: "stdout".into(),
        }
    }

    fn run_src(src: Rc<dyn LineSource>, code: &str, limits: Limits) -> Outcome {
        run(code, &meta(), src, &limits).expect("engine ran").0
    }

    fn ok(out: Outcome) -> String {
        match out {
            Outcome::Ok(s) => s,
            other => panic!("expected success, got {other:?}"),
        }
    }

    #[test]
    fn computes_an_aggregate_without_returning_the_body() {
        let src = VecSource::stdout(&["ERROR a", "ok b", "ERROR c"]);
        let out = ok(run_src(
            src,
            "let n = 0; toz.eachLine(l => { if (l.startsWith('ERROR')) n++ }); print(n)",
            Limits::default(),
        ));
        assert_eq!(out.trim(), "2");
    }

    #[test]
    fn host_access_identifiers_are_undefined() {
        // The security claim is that these were never installed, so the test is that the names do
        // not resolve — not that some deny-list rejected them.
        for name in [
            "require",
            "fetch",
            "process",
            "setTimeout",
            "setInterval",
            "XMLHttpRequest",
            "WebAssembly",
            "Deno",
        ] {
            let out = ok(run_src(
                VecSource::stdout(&[]),
                &format!("print(typeof {name})"),
                Limits::default(),
            ));
            assert_eq!(out.trim(), "undefined", "{name} should not exist");
        }
    }

    #[test]
    fn dynamic_import_cannot_resolve() {
        let out = run_src(
            VecSource::stdout(&[]),
            "import('fs').then(() => print('loaded'), e => print('blocked'))",
            Limits::default(),
        );
        match out {
            Outcome::Ok(s) => assert!(!s.contains("loaded"), "import resolved: {s}"),
            Outcome::Exception(_) => {}
            other => panic!("unexpected {other:?}"),
        }
    }

    #[test]
    fn runaway_loop_hits_the_timeout() {
        let out = run_src(
            VecSource::stdout(&[]),
            "while (true) {}",
            Limits {
                timeout_ms: 150,
                ..Limits::default()
            },
        );
        assert!(matches!(out, Outcome::Timeout), "got {out:?}");
    }

    #[test]
    fn unbounded_allocation_hits_the_memory_limit() {
        let out = run_src(
            VecSource::stdout(&[]),
            "const a = []; for (;;) { a.push(new Array(4096).fill(7)) }",
            Limits {
                memory_bytes: 8 * 1024 * 1024,
                timeout_ms: 10_000,
                ..Limits::default()
            },
        );
        assert!(matches!(out, Outcome::MemoryLimit), "got {out:?}");
    }

    #[test]
    fn excess_output_hits_the_output_limit() {
        let out = run_src(
            VecSource::stdout(&[]),
            "for (let i = 0; i < 100000; i++) print('xxxxxxxxxxxxxxxxxxxx')",
            Limits {
                max_output_bytes: 1024,
                ..Limits::default()
            },
        );
        assert!(matches!(out, Outcome::OutputLimit), "got {out:?}");
    }

    #[test]
    fn text_over_the_limit_points_at_each_line() {
        let src = VecSource::stdout(&["aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc"]);
        let out = run_src(
            src,
            "print(toz.text().length)",
            Limits {
                max_text_bytes: 12,
                ..Limits::default()
            },
        );
        match out {
            Outcome::Exception(m) => assert!(m.contains("eachLine"), "unhelpful message: {m}"),
            other => panic!("expected exception, got {other:?}"),
        }
    }

    #[test]
    fn capture_metadata_is_visible() {
        let out = ok(run_src(
            VecSource::stdout(&[]),
            "print(toz.handle.handle, toz.handle.label, toz.handle.bytes, toz.handle.exitCode)",
            Limits::default(),
        ));
        assert_eq!(out.trim(), "a1b2 git log 42 0");
    }

    #[test]
    fn json_and_regex_are_available() {
        let src = VecSource::stdout(&[r#"{"status": 500}"#, r#"{"status": 200}"#]);
        let out = ok(run_src(
            src,
            "const c = {}; toz.eachLine(l => { const s = JSON.parse(l).status; c[s] = (c[s]||0)+1 }); print(c)",
            Limits::default(),
        ));
        assert!(out.contains("\"500\""), "got {out}");
    }

    #[test]
    fn a_throw_inside_each_line_surfaces_as_that_exception() {
        let out = run_src(
            VecSource::stdout(&["a", "b"]),
            "toz.eachLine(l => { throw new Error('boom ' + l) })",
            Limits::default(),
        );
        match out {
            Outcome::Exception(m) => assert!(m.contains("boom a"), "lost the message: {m}"),
            other => panic!("expected exception, got {other:?}"),
        }
    }

    #[test]
    fn a_named_stream_overrides_the_default() {
        let src: Rc<dyn LineSource> = Rc::new(VecSource {
            stdout: vec!["out".into()],
            stderr: vec!["err1".into(), "err2".into()],
        });
        let out = ok(run_src(
            src,
            "let n = 0; toz.eachLine('stderr', () => n++); print(n)",
            Limits::default(),
        ));
        assert_eq!(out.trim(), "2");
    }

    #[test]
    fn record_calls_are_collected_in_order_grouped_by_kind() {
        let src = VecSource::stdout(&["a", "b"]);
        let (outcome, records) = run(
            "toz.record('line', {v: 1}); toz.record('other', {v: 'x'}); toz.record('line', {v: 2});",
            &meta(),
            src,
            &Limits::default(),
        )
        .expect("engine ran");
        assert!(matches!(outcome, Outcome::Ok(_)));
        let kinds: Vec<&str> = records.iter().map(|r| r.kind.as_str()).collect();
        assert_eq!(kinds, vec!["line", "other", "line"]);
        assert_eq!(records[0].json, "{\"v\":1}");
        assert_eq!(records[2].json, "{\"v\":2}");
    }

    #[test]
    #[ignore]
    fn profile_script_step_stays_under_500ms_in_release_for_1mb_input() {
        let text: String = (0..25_000)
            .map(|i| format!("line {i} payload payload payload payload\n"))
            .collect();
        assert!(
            text.len() > 1_000_000,
            "fixture must be >= 1MB, got {}",
            text.len()
        );
        let lines: Vec<&str> = text.lines().collect();
        let src = VecSource::stdout(&lines);
        let limits = Limits {
            timeout_ms: 1_000,
            memory_bytes: 64 * 1024 * 1024,
            max_output_bytes: 4 * 1024,
            ..Limits::default()
        };
        let start = Instant::now();
        let (outcome, records) = run(
            "let n = 0; toz.eachLine(l => { n++; toz.record('line', {n}); }); print('ok ' + n)",
            &meta(),
            src,
            &limits,
        )
        .expect("engine ran");
        let elapsed = start.elapsed();
        assert!(
            matches!(outcome, Outcome::Ok(_)),
            "expected success, got {outcome:?}"
        );
        assert_eq!(records.len(), lines.len());
        assert!(elapsed.as_millis() < 500, "profile step took {elapsed:?}");
    }
}
