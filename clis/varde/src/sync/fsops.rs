use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_SIBLING_ID: AtomicU64 = AtomicU64::new(0);

fn sibling_path(destination: &Path, kind: &str) -> io::Result<PathBuf> {
    let parent = destination
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let name = destination
        .file_name()
        .unwrap_or(destination.as_os_str())
        .to_string_lossy();

    for _ in 0..100 {
        let id = NEXT_SIBLING_ID.fetch_add(1, Ordering::Relaxed);
        let candidate = parent.join(format!(".{name}.varde-{kind}-{}-{id}", std::process::id()));
        match fs::symlink_metadata(&candidate) {
            Ok(_) => continue,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(candidate),
            Err(error) => return Err(error),
        }
    }

    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        format!(
            "could not find a temporary sibling for {}",
            destination.display()
        ),
    ))
}

fn remove_path(path: &Path) -> io::Result<()> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error),
    };
    if metadata.file_type().is_dir() {
        fs::remove_dir_all(path)
    } else {
        fs::remove_file(path)
    }
}

fn replace_path(
    destination: &Path,
    prepare: impl FnOnce(&Path) -> io::Result<()>,
) -> io::Result<()> {
    let parent = destination
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;

    let staged = sibling_path(destination, "stage")?;
    if let Err(error) = prepare(&staged) {
        let _ = remove_path(&staged);
        return Err(error);
    }

    let backup = match fs::symlink_metadata(destination) {
        Ok(_) => {
            let backup = sibling_path(destination, "backup")?;
            if let Err(error) = fs::rename(destination, &backup) {
                let _ = remove_path(&staged);
                return Err(error);
            }
            Some(backup)
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => None,
        Err(error) => {
            let _ = remove_path(&staged);
            return Err(error);
        }
    };

    if let Err(error) = fs::rename(&staged, destination) {
        let rollback_error = backup
            .as_ref()
            .and_then(|backup| fs::rename(backup, destination).err());
        let _ = remove_path(&staged);
        let message = match rollback_error {
            Some(rollback) => format!(
                "could not install {}: {error}; could not restore its backup: {rollback}",
                destination.display()
            ),
            None if backup.is_some() => format!(
                "could not install {}: {error}; restored its previous copy",
                destination.display()
            ),
            None => format!("could not install {}: {error}", destination.display()),
        };
        return Err(io::Error::new(error.kind(), message));
    }

    if let Some(backup) = backup {
        let _ = remove_path(&backup);
    }
    Ok(())
}

/// Write a complete directory beside its destination and swap it into place.
/// If the staged rename fails, the previous destination is restored.
pub fn replace_directory(
    destination: &Path,
    populate: impl FnOnce(&Path) -> io::Result<()>,
) -> io::Result<()> {
    replace_path(destination, |staged| {
        fs::create_dir(staged)?;
        populate(staged)
    })
}

/// Write a regular file beside its destination and swap it into place.
/// If the staged rename fails, the previous destination is restored.
pub fn replace_file(destination: &Path, contents: &[u8]) -> io::Result<()> {
    replace_path(destination, |staged| write_file(staged, contents, false))
}

/// Replace a destination with a directory copy without following symlinks.
pub fn replace_with_copy(destination: &Path, source: &Path) -> io::Result<()> {
    replace_directory(destination, |staged| copy_directory(source, staged))
}

/// Replace a destination with a directory symlink.
pub fn replace_with_symlink(destination: &Path, target: &Path) -> io::Result<()> {
    replace_path(destination, |staged| {
        create_directory_symlink(target, staged)
    })
}

/// Replace a destination with a file symlink.
pub fn replace_with_file_symlink(destination: &Path, target: &Path) -> io::Result<()> {
    replace_path(destination, |staged| create_file_symlink(target, staged))
}

/// Recursively copy regular files and directories. Symlinks and special files
/// are rejected so a caller never copies through a foreign link.
pub fn copy_directory(source: &Path, destination: &Path) -> io::Result<()> {
    let source_metadata = fs::symlink_metadata(source)?;
    if !source_metadata.file_type().is_dir() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("copy source {} is not a real directory", source.display()),
        ));
    }
    fs::create_dir_all(destination)?;

    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let source_path = entry.path();
        let destination_path = destination.join(entry.file_name());
        let file_type = entry.file_type()?;
        if file_type.is_dir() {
            copy_directory(&source_path, &destination_path)?;
        } else if file_type.is_file() {
            fs::copy(&source_path, &destination_path)?;
        } else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!(
                    "refusing to copy symlink or special file {}",
                    source_path.display()
                ),
            ));
        }
    }
    Ok(())
}

/// Write an embedded regular file with a stable executable/non-executable mode.
pub fn write_file(path: &Path, contents: &[u8], executable: bool) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, contents)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        let mode = if executable { 0o755 } else { 0o644 };
        fs::set_permissions(path, fs::Permissions::from_mode(mode))?;
    }
    #[cfg(not(unix))]
    let _ = executable;

    Ok(())
}

fn create_directory_symlink(target: &Path, link: &Path) -> io::Result<()> {
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(target, link)
    }
    #[cfg(windows)]
    {
        std::os::windows::fs::symlink_dir(target, link)
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = (target, link);
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "directory symlinks are unsupported on this platform",
        ))
    }
}

fn create_file_symlink(target: &Path, link: &Path) -> io::Result<()> {
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(target, link)
    }
    #[cfg(windows)]
    {
        std::os::windows::fs::symlink_file(target, link)
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = (target, link);
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "file symlinks are unsupported on this platform",
        ))
    }
}
