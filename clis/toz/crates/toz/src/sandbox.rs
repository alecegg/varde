//! OS sandbox for an untrusted worker and every process it starts.

use anyhow::{ensure, Context, Result};
use std::collections::BTreeSet;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug, Clone)]
pub(crate) struct Policy {
    pub read_roots: Vec<PathBuf>,
    pub write_roots: Vec<PathBuf>,
    pub scratch_dir: PathBuf,
    pub network: bool,
    /// Additional host environment variable names to pass to the worker.
    pub env_allow: Vec<String>,
    /// Store and raw-output locations owned by the trusted parent.
    pub protected_roots: Vec<PathBuf>,
}

struct CheckedPolicy {
    read_roots: Vec<PathBuf>,
    write_roots: Vec<PathBuf>,
    scratch_dir: PathBuf,
    network: bool,
    executable: PathBuf,
    cwd: PathBuf,
    protected_roots: Vec<PathBuf>,
}

impl Policy {
    fn check(&self, executable: &Path, cwd: &Path) -> Result<CheckedPolicy> {
        let read_roots = canonical_roots(&self.read_roots)?;
        let write_roots = canonical_roots(&self.write_roots)?;
        let protected_roots: Vec<_> = self
            .protected_roots
            .iter()
            .map(|path| {
                path.canonicalize()
                    .with_context(|| format!("resolving protected store {}", path.display()))
            })
            .collect::<Result<_>>()?;
        ensure!(
            !protected_roots.is_empty(),
            "sandbox policy requires a protected store path"
        );
        check_protected_system_roots(&protected_roots)?;
        let scratch_dir = canonical_dir(&self.scratch_dir)?;
        let executable = executable
            .canonicalize()
            .with_context(|| format!("resolving worker executable {}", executable.display()))?;
        ensure!(executable.is_file(), "worker executable must be a file");
        let cwd = canonical_dir(cwd)?;

        check_protected_access(&read_roots, &write_roots, &scratch_dir, &protected_roots)?;
        ensure!(
            !protected_roots
                .iter()
                .any(|root| executable.starts_with(root)),
            "worker executable is inside the protected store"
        );
        ensure!(
            read_roots
                .iter()
                .chain(write_roots.iter())
                .any(|root| cwd.starts_with(root))
                || cwd.starts_with(&scratch_dir),
            "worker directory {} is not permitted by sandbox policy",
            cwd.display()
        );

        Ok(CheckedPolicy {
            read_roots,
            write_roots,
            scratch_dir,
            network: self.network,
            executable,
            cwd,
            protected_roots,
        })
    }
}

fn check_protected_system_roots(protected_roots: &[PathBuf]) -> Result<()> {
    for protected in protected_roots {
        for system in system_read_roots() {
            ensure!(
                !protected.starts_with(Path::new(system)),
                "protected store {} is inside required system path {}",
                protected.display(),
                system
            );
        }
    }
    Ok(())
}

fn check_protected_access(
    read_roots: &[PathBuf],
    write_roots: &[PathBuf],
    scratch_dir: &Path,
    protected_roots: &[PathBuf],
) -> Result<()> {
    for granted in read_roots
        .iter()
        .chain(write_roots.iter())
        .map(PathBuf::as_path)
        .chain(std::iter::once(scratch_dir))
    {
        for protected in protected_roots {
            ensure!(
                !granted.starts_with(protected) && !protected.starts_with(granted),
                "sandbox access to {} overlaps protected store {}",
                granted.display(),
                protected.display()
            );
        }
    }
    Ok(())
}

fn system_read_roots() -> &'static [&'static str] {
    // Kept separate from policy roots so a store inside an implicit runtime mount fails closed.
    #[cfg(target_os = "macos")]
    const ROOTS: &[&str] = &[
        "/System",
        "/usr",
        "/bin",
        "/sbin",
        "/Library",
        "/private/var/db/dyld",
        "/private/etc/ssl",
    ];
    #[cfg(target_os = "linux")]
    const ROOTS: &[&str] = &[
        "/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc/ssl", "/etc/pki",
    ];
    ROOTS
}

fn canonical_roots(roots: &[PathBuf]) -> Result<Vec<PathBuf>> {
    roots.iter().map(|path| canonical_dir(path)).collect()
}

fn canonical_dir(path: &Path) -> Result<PathBuf> {
    let path = path
        .canonicalize()
        .with_context(|| format!("resolving sandbox path {}", path.display()))?;
    ensure!(
        path.is_dir(),
        "sandbox path {} is not a directory",
        path.display()
    );
    Ok(path)
}

/// Build a command that runs the executable and all descendants under one OS policy.
/// The caller owns standard streams, environment, and process-group management.
pub(crate) fn sandboxed_command(
    executable: &Path,
    args: &[OsString],
    policy: &Policy,
    cwd: &Path,
) -> Result<Command> {
    let checked = policy.check(executable, cwd)?;
    #[cfg(target_os = "macos")]
    let mut command = macos_command(&checked, args)?;
    #[cfg(target_os = "linux")]
    let mut command = linux_command(&checked, args)?;
    #[cfg(any(target_os = "macos", target_os = "linux"))]
    {
        command.env_clear();
        for name in ["PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM"]
            .into_iter()
            .chain(policy.env_allow.iter().map(String::as_str))
        {
            ensure!(
                valid_env_name(name),
                "invalid sandbox environment variable name {name:?}"
            );
            if let Some(value) = std::env::var_os(name) {
                command.env(name, value);
            }
        }
        Ok(command)
    }
    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    anyhow::bail!("toz sandbox is unsupported on this platform")
}

fn valid_env_name(name: &str) -> bool {
    let mut chars = name.bytes();
    matches!(chars.next(), Some(b'A'..=b'Z' | b'a'..=b'z' | b'_'))
        && chars.all(|c| c.is_ascii_alphanumeric() || c == b'_')
}

#[cfg(target_os = "macos")]
fn macos_command(policy: &CheckedPolicy, args: &[OsString]) -> Result<Command> {
    let launcher = Path::new("/usr/bin/sandbox-exec");
    ensure!(launcher.is_file(), "Seatbelt sandbox-exec is unavailable");
    let profile = seatbelt_profile(policy)?;
    let mut command = Command::new(launcher);
    command
        .arg("-p")
        .arg(profile)
        .arg(&policy.executable)
        .args(args);
    command.current_dir(&policy.cwd);
    Ok(command)
}

#[cfg(target_os = "macos")]
fn seatbelt_profile(policy: &CheckedPolicy) -> Result<String> {
    let mut profile = String::from(
        "(version 1)\n(deny default)\n(allow process-exec*)\n(allow process-fork)\n(allow process-info* (target self))\n(allow sysctl-read)\n",
    );
    profile.push_str(
        "(allow file-read-metadata (subpath \"/\"))\n(allow file-read-data (literal \"/\"))\n",
    );
    // Read-only OS paths needed by the loader and ordinary command-line programs.
    let mut reads: BTreeSet<PathBuf> = [
        "/System",
        "/usr",
        "/bin",
        "/sbin",
        "/Library",
        "/private/var/db/dyld",
        "/private/etc/ssl",
    ]
    .into_iter()
    .map(PathBuf::from)
    .collect();
    reads.extend(policy.read_roots.iter().cloned());
    reads.extend(policy.write_roots.iter().cloned());
    reads.insert(policy.scratch_dir.clone());
    reads.insert(policy.executable.clone());
    for path in reads {
        profile.push_str(&format!(
            "(allow file-read* (subpath {}))\n",
            seatbelt_path(&path)?
        ));
    }
    for path in ["/dev/null", "/dev/random", "/dev/urandom", "/dev/tty"] {
        profile.push_str(&format!("(allow file-read* (literal \"{path}\"))\n"));
    }
    for path in policy
        .write_roots
        .iter()
        .chain(std::iter::once(&policy.scratch_dir))
    {
        profile.push_str(&format!(
            "(allow file-write* (subpath {}))\n",
            seatbelt_path(path)?
        ));
    }
    profile.push_str("(allow file-write* (literal \"/dev/null\"))\n");
    profile.push_str("(allow file-write* (literal \"/dev/tty\"))\n");
    if policy.network {
        profile.push_str("(allow network*)\n(allow mach-lookup)\n");
    }
    for path in &policy.protected_roots {
        profile.push_str(&format!(
            "(deny file-read* file-write* (subpath {}))\n",
            seatbelt_path(path)?
        ));
    }
    Ok(profile)
}

#[cfg(target_os = "macos")]
fn seatbelt_path(path: &Path) -> Result<String> {
    let value = path
        .to_str()
        .context("non-UTF-8 sandbox path is unsupported")?;
    ensure!(
        !value.chars().any(char::is_control),
        "control character in sandbox path"
    );
    Ok(format!(
        "\"{}\"",
        value.replace('\\', "\\\\").replace('"', "\\\"")
    ))
}

#[cfg(target_os = "linux")]
fn linux_command(policy: &CheckedPolicy, args: &[OsString]) -> Result<Command> {
    let launcher = find_bwrap().context("Bubblewrap is required to run sandboxed scripts")?;
    let mut command = Command::new(launcher);
    command.args(["--unshare-all", "--die-with-parent", "--new-session"]);
    if policy.network {
        command.arg("--share-net");
    }
    command.args(["--tmpfs", "/", "--proc", "/proc", "--dev", "/dev"]);

    let mut reads: BTreeSet<PathBuf> = ["/usr", "/bin", "/sbin", "/lib", "/lib64"]
        .into_iter()
        .map(PathBuf::from)
        .filter(|path| path.exists())
        .collect();
    if policy.network {
        reads.extend(
            [
                "/etc/resolv.conf",
                "/etc/hosts",
                "/etc/nsswitch.conf",
                "/etc/ssl",
                "/etc/pki",
            ]
            .into_iter()
            .map(PathBuf::from)
            .filter(|path| path.exists()),
        );
    }
    reads.extend(policy.read_roots.iter().cloned());
    reads.insert(policy.executable.clone());
    let mut writes: BTreeSet<PathBuf> = policy.write_roots.iter().cloned().collect();
    writes.insert(policy.scratch_dir.clone());
    // Create mount parents before binding paths outside the system directories.
    let mut dirs = BTreeSet::new();
    for path in reads.iter().chain(writes.iter()) {
        for parent in path.ancestors().skip(1).filter(|p| *p != Path::new("/")) {
            dirs.insert(parent.to_path_buf());
        }
    }
    let mut dirs: Vec<_> = dirs.into_iter().collect();
    dirs.sort_by_key(|path| path.components().count());
    for dir in dirs {
        command.arg("--dir").arg(dir);
    }
    for path in reads.difference(&writes).filter(|path| {
        !reads
            .iter()
            .any(|other| *path != other && path.starts_with(other))
            && !writes.iter().any(|other| path.starts_with(other))
    }) {
        command.arg("--ro-bind").arg(path).arg(path);
    }
    for path in writes {
        command.arg("--bind").arg(&path).arg(&path);
    }
    command.arg("--chdir").arg(&policy.cwd);
    command.arg("--").arg(&policy.executable).args(args);
    Ok(command)
}

#[cfg(target_os = "linux")]
fn find_bwrap() -> Option<PathBuf> {
    std::env::split_paths(&std::env::var_os("PATH")?)
        .map(|dir| dir.join("bwrap"))
        .find(|path| path.is_file())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_store_overlap() {
        let temp = tempfile::tempdir().unwrap();
        let store = temp.path().join("store");
        let scratch = temp.path().join("scratch");
        std::fs::create_dir(&store).unwrap();
        std::fs::create_dir(&scratch).unwrap();
        let policy = Policy {
            read_roots: vec![temp.path().to_path_buf()],
            write_roots: vec![],
            scratch_dir: scratch,
            network: false,
            env_allow: vec![],
            protected_roots: vec![store],
        };
        assert!(policy.check(Path::new("/bin/sh"), temp.path()).is_err());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn seatbelt_network_is_opt_in() {
        let temp = tempfile::tempdir().unwrap();
        let policy = CheckedPolicy {
            read_roots: vec![temp.path().to_path_buf()],
            write_roots: vec![],
            scratch_dir: temp.path().to_path_buf(),
            network: false,
            executable: PathBuf::from("/bin/echo"),
            cwd: temp.path().to_path_buf(),
            protected_roots: vec![],
        };
        let profile = seatbelt_profile(&policy).unwrap();
        assert!(!profile.contains("(allow network*)"));
        assert!(profile.contains("(deny default)"));
    }

    #[cfg(target_os = "macos")]
    #[test]
    #[ignore = "nested Seatbelt is unavailable in some test harnesses"]
    fn seatbelt_runs_harmless_command() {
        let temp = tempfile::tempdir().unwrap();
        let scratch = temp.path().join("scratch");
        let store = temp.path().join("store");
        std::fs::create_dir(&scratch).unwrap();
        std::fs::create_dir(&store).unwrap();
        let policy = Policy {
            read_roots: vec![],
            write_roots: vec![],
            scratch_dir: scratch.clone(),
            network: false,
            env_allow: vec![],
            protected_roots: vec![store],
        };
        let output = sandboxed_command(
            Path::new("/bin/echo"),
            &[OsString::from("ok")],
            &policy,
            &scratch,
        )
        .unwrap()
        .output()
        .unwrap();
        assert!(
            output.status.success(),
            "status: {}; stderr: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        );
        let child = sandboxed_command(
            Path::new("/bin/sh"),
            &[OsString::from("-c"), OsString::from("/bin/echo child")],
            &policy,
            &scratch,
        )
        .unwrap()
        .output()
        .unwrap();
        assert!(
            child.status.success(),
            "{}",
            String::from_utf8_lossy(&child.stderr)
        );
        assert_eq!(child.stdout, b"child\n");
        let secret_name = "TOZ_SANDBOX_SECRET_PROBE";
        std::env::set_var(secret_name, "hidden");
        let environment = sandboxed_command(Path::new("/usr/bin/env"), &[], &policy, &scratch)
            .unwrap()
            .output()
            .unwrap();
        std::env::remove_var(secret_name);
        assert!(environment.status.success());
        assert!(!String::from_utf8_lossy(&environment.stdout).contains(secret_name));
        let secret = temp.path().join("store/secret");
        std::fs::write(&secret, "blocked").unwrap();
        let denied = sandboxed_command(
            Path::new("/bin/cat"),
            &[secret.into_os_string()],
            &policy,
            &scratch,
        )
        .unwrap()
        .output()
        .unwrap();
        assert!(!denied.status.success());
        assert!(!String::from_utf8_lossy(&denied.stdout).contains("blocked"));
    }
}
