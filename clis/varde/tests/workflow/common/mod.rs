//! Shared helpers for CLI integration tests.

use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_TEMP_DIR: AtomicU64 = AtomicU64::new(0);

pub fn bin() -> &'static str {
    env!("CARGO_BIN_EXE_varde")
}

/// A `varde` command that routes its first argument to its owning group when
/// it runs (`plan`, `knowledge`, `doc` or `setup`).
#[allow(dead_code)]
pub struct WorkCommand {
    command: Command,
    args: Vec<OsString>,
}

#[allow(dead_code)]
impl WorkCommand {
    fn group(&self) -> &'static str {
        match self.args.first().and_then(|arg| arg.to_str()) {
            Some("concept" | "lint") => "knowledge",
            Some("spec") => "doc",
            Some("paths" | "instructions") => "setup",
            _ => "plan",
        }
    }

    fn routed(&mut self) -> &mut Command {
        let group = self.group();
        let args = std::mem::take(&mut self.args);
        self.command.args([group]).args(args)
    }

    pub fn arg(&mut self, arg: impl AsRef<OsStr>) -> &mut Self {
        self.args.push(arg.as_ref().to_owned());
        self
    }

    pub fn args<I, S>(&mut self, args: I) -> &mut Self
    where
        I: IntoIterator<Item = S>,
        S: AsRef<OsStr>,
    {
        self.args
            .extend(args.into_iter().map(|arg| arg.as_ref().to_owned()));
        self
    }

    pub fn current_dir(&mut self, dir: impl AsRef<Path>) -> &mut Self {
        self.command.current_dir(dir);
        self
    }

    pub fn env(&mut self, key: impl AsRef<OsStr>, value: impl AsRef<OsStr>) -> &mut Self {
        self.command.env(key, value);
        self
    }

    pub fn envs<I, K, V>(&mut self, vars: I) -> &mut Self
    where
        I: IntoIterator<Item = (K, V)>,
        K: AsRef<OsStr>,
        V: AsRef<OsStr>,
    {
        self.command.envs(vars);
        self
    }

    pub fn env_remove(&mut self, key: impl AsRef<OsStr>) -> &mut Self {
        self.command.env_remove(key);
        self
    }

    pub fn stdin(&mut self, stdin: Stdio) -> &mut Self {
        self.command.stdin(stdin);
        self
    }

    pub fn stdout(&mut self, stdout: Stdio) -> &mut Self {
        self.command.stdout(stdout);
        self
    }

    pub fn stderr(&mut self, stderr: Stdio) -> &mut Self {
        self.command.stderr(stderr);
        self
    }

    pub fn output(&mut self) -> std::io::Result<Output> {
        self.routed().output()
    }

    pub fn spawn(&mut self) -> std::io::Result<Child> {
        self.routed().spawn()
    }
}

#[allow(dead_code)]
pub fn work_command() -> WorkCommand {
    WorkCommand {
        command: Command::new(bin()),
        args: Vec::new(),
    }
}

/// Run a CLI fixture with an isolated default memory configuration.
pub fn isolate_memory(root: &Path) -> WorkCommand {
    let mut command = work_command();
    command
        .current_dir(root)
        .env("VARDE_CONFIG_DIR", root.join("isolated-config"))
        .env_remove("VARDE_WORKING_DIR")
        .env_remove("VARDE_KNOWLEDGE_DIR")
        .env_remove("VARDE_LEARN_STORE");
    command
}

/// Collect CPU usage for one CLI child without counting children started by
/// parallel integration tests in this test process.
#[cfg(unix)]
#[allow(dead_code)]
pub fn output_with_child_cpu_time(mut command: WorkCommand) -> (Output, std::time::Duration) {
    use std::io::{Read, Seek, SeekFrom};
    use std::os::unix::process::ExitStatusExt;

    let mut stdout = tempfile::tempfile().expect("create child stdout file");
    let mut stderr = tempfile::tempfile().expect("create child stderr file");
    command.stdout(Stdio::from(stdout.try_clone().expect("clone stdout file")));
    command.stderr(Stdio::from(stderr.try_clone().expect("clone stderr file")));
    let child = command.spawn().expect("spawn CLI child");
    let child_pid = child.id() as libc::pid_t;
    let mut status = std::mem::MaybeUninit::<libc::c_int>::uninit();
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();

    loop {
        let waited = unsafe { libc::wait4(child_pid, status.as_mut_ptr(), 0, usage.as_mut_ptr()) };
        if waited == child_pid {
            break;
        }
        let error = std::io::Error::last_os_error();
        if waited == -1 && error.kind() == std::io::ErrorKind::Interrupted {
            continue;
        }
        panic!("wait4({child_pid}) failed: {error}");
    }

    let status = unsafe { status.assume_init() };
    let usage = unsafe { usage.assume_init() };
    let mut stdout_bytes = Vec::new();
    let mut stderr_bytes = Vec::new();
    stdout
        .seek(SeekFrom::Start(0))
        .and_then(|_| stdout.read_to_end(&mut stdout_bytes))
        .expect("read child stdout file");
    stderr
        .seek(SeekFrom::Start(0))
        .and_then(|_| stderr.read_to_end(&mut stderr_bytes))
        .expect("read child stderr file");

    let cpu_time = |time: libc::timeval| {
        std::time::Duration::new(
            time.tv_sec.max(0) as u64,
            time.tv_usec.max(0) as u32 * 1_000,
        )
    };
    (
        Output {
            status: std::process::ExitStatus::from_raw(status),
            stdout: stdout_bytes,
            stderr: stderr_bytes,
        },
        cpu_time(usage.ru_utime) + cpu_time(usage.ru_stime),
    )
}

#[allow(dead_code)]
pub fn json_data(bytes: &[u8]) -> serde_json::Value {
    let envelope: serde_json::Value = serde_json::from_slice(bytes).unwrap();
    assert_eq!(envelope["schema_version"], 1);
    assert_eq!(envelope["envelope_version"], 1);
    assert_eq!(envelope["ok"], true);
    assert_eq!(envelope["outcome"], "success");
    assert!(envelope["meta"].is_object());
    envelope["data"].clone()
}

/// A fresh, empty bundle directory unique to this test run.
pub fn temp_bundle(tag: &str) -> PathBuf {
    create_temp_dir("ck-test", tag)
}

/// A directory holding input documents, kept separate from any bundle.
/// Only some test crates use it; shared helpers may be unused per crate.
#[allow(dead_code)]
pub fn temp_inputs(tag: &str) -> PathBuf {
    create_temp_dir("ck-inputs", tag)
}

fn create_temp_dir(prefix: &str, tag: &str) -> PathBuf {
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    loop {
        let nonce = NEXT_TEMP_DIR.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!(
            "{prefix}-{tag}-{}-{timestamp}-{nonce}",
            std::process::id()
        ));
        match std::fs::create_dir(&dir) {
            Ok(()) => return dir,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => panic!("could not create {}: {error}", dir.display()),
        }
    }
}
