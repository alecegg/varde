//! Embeds a build identity of this crate's sources as `VARDE_CODE_BUILD_ID`.
//!
//! The index build fingerprint (`db::build_version_fingerprint`) must agree
//! across every binary that embeds this extractor and differ when the
//! extractor changes, so it hashes the crate's inputs rather than any file on
//! disk at run time. The workspace `Cargo.lock` is hashed too, when present,
//! because dependency versions change extractor behavior.

use std::fs;
use std::path::{Path, PathBuf};

const LOCKFILE: &str = "../../../Cargo.lock";

fn main() {
    let mut files = Vec::new();
    for dir in ["src", "assets"] {
        println!("cargo:rerun-if-changed={dir}");
        collect(Path::new(dir), &mut files);
    }
    println!("cargo:rerun-if-changed=Cargo.toml");
    files.push(PathBuf::from("Cargo.toml"));
    let mut inputs = vec!["src", "assets", "Cargo.toml"];
    // Skipped silently when built outside the workspace (a published crate).
    let lockfile = Path::new(LOCKFILE);
    if lockfile.is_file() {
        println!("cargo:rerun-if-changed={LOCKFILE}");
        files.push(lockfile.to_path_buf());
        inputs.push(LOCKFILE);
    }
    files.sort();

    // FNV-1a over each relative path and its bytes.
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    let mut feed = |bytes: &[u8]| {
        for b in bytes {
            hash = (hash ^ u64::from(*b)).wrapping_mul(0x100_0000_01b3);
        }
    };
    for file in &files {
        feed(file.to_string_lossy().as_bytes());
        feed(&fs::read(file).expect("crate input is readable"));
    }
    println!("cargo:rustc-env=VARDE_CODE_BUILD_ID={hash:016x}");
    println!(
        "cargo:rustc-env=VARDE_CODE_BUILD_INPUTS={}",
        inputs.join(",")
    );
}

fn collect(dir: &Path, files: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect(&path, files);
        } else {
            files.push(path);
        }
    }
}
