//! Repository identities, including symlink ancestors of future files.
use std::collections::VecDeque;
use std::ffi::OsString;
use std::fs;
use std::io;
use std::path::{Component, Path, PathBuf};

fn components(path: &Path) -> VecDeque<OsString> {
    let mut parts: VecDeque<_> = path
        .components()
        .map(|part| part.as_os_str().to_owned())
        .collect();
    // Path::components drops terminal directory syntax. Retain that requirement
    // so an existing regular file followed by `/` or `/.` cannot be accepted.
    if path
        .to_str()
        .is_some_and(|value| value.ends_with('/') || value.ends_with("/."))
    {
        parts.push_back(OsString::from("."));
    }
    parts
}

pub fn canonical_path(root: &Path, path: &str) -> Result<String, String> {
    let candidate = root.join(path);
    let mut pending = components(&candidate);
    let mut resolved = PathBuf::new();
    let mut links = 0;
    while let Some(part) = pending.pop_front() {
        let component = Path::new(&part).components().next().unwrap();
        match component {
            Component::RootDir => resolved.push(&part),
            Component::CurDir => {}
            Component::ParentDir => {
                resolved.pop();
            }
            Component::Normal(_) => {
                let next = resolved.join(&part);
                match fs::symlink_metadata(&next) {
                    Ok(metadata) if metadata.file_type().is_symlink() => {
                        links += 1;
                        if links > 40 {
                            return Err(format!("symlink loop in {path}"));
                        }
                        let target = fs::read_link(&next).map_err(|error| error.to_string())?;
                        if target.is_absolute() {
                            resolved.clear();
                        }
                        let mut expanded = components(&target);
                        expanded.append(&mut pending);
                        pending = expanded;
                    }
                    Ok(metadata) => {
                        if !metadata.is_dir() && !pending.is_empty() {
                            return Err(format!("not a directory: {}", next.display()));
                        }
                        resolved.push(part);
                    }
                    Err(error) if error.kind() == io::ErrorKind::NotFound => resolved.push(part),
                    Err(error) => return Err(error.to_string()),
                }
            }
            Component::Prefix(_) => return Err("unsupported path prefix".into()),
        }
    }
    resolved
        .strip_prefix(root)
        .map_err(|_| format!("path escapes repository: {path}"))?
        .to_str()
        .map(str::to_owned)
        .ok_or_else(|| "path is not UTF-8".into())
}

pub fn compile_unit(root: &Path, path: &str) -> Option<String> {
    let mut directory = root.join(path).parent()?.to_owned();
    while directory.starts_with(root) {
        let fixed = ["Cargo.toml", "go.mod", "tsconfig.json", "pom.xml"];
        let found = fixed.iter().any(|marker| directory.join(marker).is_file())
            || fs::read_dir(&directory).ok().is_some_and(|entries| {
                entries.flatten().any(|entry| {
                    let name = entry.file_name();
                    let name = name.to_string_lossy();
                    name.ends_with(".csproj") || name.starts_with("build.gradle")
                })
            });
        if found {
            let relative = directory.strip_prefix(root).ok()?.to_str()?;
            return Some(if relative.is_empty() {
                ".".into()
            } else {
                relative.into()
            });
        }
        if directory == root {
            break;
        }
        directory.pop();
    }
    None
}
