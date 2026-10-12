//! Repository identities, including symlink ancestors of future files.
use std::collections::VecDeque;
use std::ffi::OsString;
use std::fs;
use std::io;
use std::path::{Component, Path, PathBuf};

#[derive(Clone, Debug, Eq, PartialEq)]
enum PatternPart {
    Segment(String),
    Recursive,
}

fn pattern_parts(pattern: &str) -> Vec<PatternPart> {
    let directory = pattern.ends_with('/');
    let body = pattern.strip_suffix('/').unwrap_or(pattern);
    let mut parts: Vec<_> = body
        .split('/')
        .map(|part| {
            if part == "**" {
                PatternPart::Recursive
            } else {
                PatternPart::Segment(part.to_owned())
            }
        })
        .collect();
    if directory {
        parts.extend([PatternPart::Segment("*".into()), PatternPart::Recursive]);
    }
    parts
}

fn segment_matches(pattern: &str, path: &str) -> bool {
    let pattern: Vec<_> = pattern.chars().collect();
    let path: Vec<_> = path.chars().collect();
    let mut matches = vec![false; path.len() + 1];
    matches[0] = true;
    for token in pattern {
        let mut next = vec![false; path.len() + 1];
        if token == '*' {
            next[0] = matches[0];
            for index in 1..=path.len() {
                next[index] = matches[index] || next[index - 1];
            }
        } else {
            for index in 1..=path.len() {
                next[index] = matches[index - 1] && path[index - 1] == token;
            }
        }
        matches = next;
    }
    matches[path.len()]
}

fn segment_overlap(left: &str, right: &str) -> bool {
    let left: Vec<_> = left.chars().collect();
    let right: Vec<_> = right.chars().collect();
    let alphabet: std::collections::BTreeSet<_> = left
        .iter()
        .chain(&right)
        .copied()
        .filter(|character| *character != '*')
        .chain(['a'])
        .collect();
    let mut pending = VecDeque::from([(0, 0, false)]);
    let mut seen = std::collections::HashSet::new();
    while let Some((left_index, right_index, nonempty)) = pending.pop_front() {
        if !seen.insert((left_index, right_index, nonempty)) {
            continue;
        }
        if left_index == left.len() && right_index == right.len() && nonempty {
            return true;
        }
        if left.get(left_index) == Some(&'*') {
            pending.push_back((left_index + 1, right_index, nonempty));
        }
        if right.get(right_index) == Some(&'*') {
            pending.push_back((left_index, right_index + 1, nonempty));
        }
        for character in &alphabet {
            let next_left = match left.get(left_index) {
                Some('*') => Some(left_index),
                Some(expected) if expected == character => Some(left_index + 1),
                _ => None,
            };
            let next_right = match right.get(right_index) {
                Some('*') => Some(right_index),
                Some(expected) if expected == character => Some(right_index + 1),
                _ => None,
            };
            if let (Some(next_left), Some(next_right)) = (next_left, next_right) {
                pending.push_back((next_left, next_right, true));
            }
        }
    }
    false
}

fn parts_overlap(left: &[PatternPart], right: &[PatternPart]) -> bool {
    let mut pending = VecDeque::from([(0, 0, false)]);
    let mut seen = std::collections::HashSet::new();
    while let Some((left_index, right_index, nonempty)) = pending.pop_front() {
        if !seen.insert((left_index, right_index, nonempty)) {
            continue;
        }
        if left_index == left.len() && right_index == right.len() && nonempty {
            return true;
        }
        if left.get(left_index) == Some(&PatternPart::Recursive) {
            pending.push_back((left_index + 1, right_index, nonempty));
        }
        if right.get(right_index) == Some(&PatternPart::Recursive) {
            pending.push_back((left_index, right_index + 1, nonempty));
        }
        match (left.get(left_index), right.get(right_index)) {
            (Some(PatternPart::Recursive), Some(PatternPart::Recursive)) => {
                pending.push_back((left_index, right_index, true));
            }
            (Some(PatternPart::Recursive), Some(PatternPart::Segment(segment)))
                if segment_overlap("*", segment) =>
            {
                pending.push_back((left_index, right_index + 1, true));
            }
            (Some(PatternPart::Segment(segment)), Some(PatternPart::Recursive))
                if segment_overlap(segment, "*") =>
            {
                pending.push_back((left_index + 1, right_index, true));
            }
            (Some(PatternPart::Segment(a)), Some(PatternPart::Segment(b)))
                if segment_overlap(a, b) =>
            {
                pending.push_back((left_index + 1, right_index + 1, true));
            }
            _ => {}
        }
    }
    false
}

/// Whether a repository-relative changed path is covered by one declaration.
pub fn matches_declaration(declaration: &str, path: &str) -> bool {
    if !declaration.contains('*') && !declaration.ends_with('/') {
        return declaration == path;
    }
    fn matches(
        pattern: &[PatternPart],
        path: &[&str],
        pattern_index: usize,
        path_index: usize,
        memo: &mut std::collections::HashMap<(usize, usize), bool>,
    ) -> bool {
        if let Some(result) = memo.get(&(pattern_index, path_index)) {
            return *result;
        }
        let result = match pattern.get(pattern_index) {
            None => path_index == path.len(),
            Some(PatternPart::Recursive) => {
                matches(pattern, path, pattern_index + 1, path_index, memo)
                    || (path_index < path.len()
                        && matches(pattern, path, pattern_index, path_index + 1, memo))
            }
            Some(PatternPart::Segment(segment)) => {
                path_index < path.len()
                    && segment_matches(segment, path[path_index])
                    && matches(pattern, path, pattern_index + 1, path_index + 1, memo)
            }
        };
        memo.insert((pattern_index, path_index), result);
        result
    }
    let pattern = pattern_parts(declaration);
    let path: Vec<_> = path.split('/').collect();
    matches(&pattern, &path, 0, 0, &mut std::collections::HashMap::new())
}

/// Whether two declarations can cover at least one repository-relative path.
pub fn declarations_overlap(left: &str, right: &str) -> bool {
    parts_overlap(&pattern_parts(left), &pattern_parts(right))
}

/// Canonicalize the literal prefix of a declaration without treating wildcard
/// components as filesystem paths.
pub fn canonical_declaration(root: &Path, declaration: &str) -> Result<String, String> {
    if Path::new(declaration).is_absolute() {
        return Err(format!("path escapes repository: {declaration}"));
    }
    let directory = declaration.ends_with('/');
    let body = declaration.strip_suffix('/').unwrap_or(declaration);
    let components: Vec<_> = body.split('/').collect();
    let Some(wildcard) = components.iter().position(|part| part.contains('*')) else {
        let path = canonical_path(root, declaration)?;
        return Ok(if directory && !path.is_empty() {
            format!("{path}/")
        } else {
            path
        });
    };
    if components[wildcard..]
        .iter()
        .any(|part| *part == "." || *part == "..")
    {
        return Err("glob declarations cannot contain `.` or `..` components".into());
    }
    let prefix = components[..wildcard].join("/");
    let prefix_path = if prefix.is_empty() {
        ".".to_owned()
    } else {
        format!("{prefix}/")
    };
    let prefix = canonical_path(root, &prefix_path)?;
    let suffix = components[wildcard..].join("/");
    let mut path = if prefix.is_empty() {
        suffix
    } else {
        format!("{prefix}/{suffix}")
    };
    if directory {
        path.push('/');
    }
    Ok(path)
}

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

/// Resolve a declaration to the repository paths it currently covers.
/// Missing literal paths and unmatched globs return an empty list; callers
/// decide whether those are valid for their declaration kind.
pub(crate) fn matching_paths(root: &Path, declaration: &str) -> Result<Vec<String>, String> {
    let declaration = canonical_declaration(root, declaration)?;
    let path = declaration.strip_suffix('/').unwrap_or(&declaration);
    if !declaration.contains('*') {
        return match fs::metadata(root.join(path)) {
            Ok(metadata) if declaration.ends_with('/') && !metadata.is_dir() => {
                Err(format!("not a directory: {declaration}"))
            }
            Ok(_) => Ok(vec![declaration]),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(Vec::new()),
            Err(error) => Err(error.to_string()),
        };
    }

    let prefix = path
        .split('/')
        .take_while(|part| !part.contains('*'))
        .collect::<Vec<_>>()
        .join("/");
    let base = if prefix.is_empty() {
        root.to_path_buf()
    } else {
        root.join(prefix)
    };
    match fs::metadata(&base) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(error.to_string()),
        Ok(metadata) if !metadata.is_dir() => {
            return Err(format!("not a directory: {}", base.display()));
        }
        Ok(_) => {}
    }

    let mut pending = vec![base];
    let mut matches = Vec::new();
    while let Some(directory) = pending.pop() {
        for entry in fs::read_dir(&directory).map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            let file_type = entry.file_type().map_err(|error| error.to_string())?;
            if file_type.is_dir() && entry.file_name() == ".git" {
                continue;
            }
            let entry_path = entry.path();
            let relative = entry_path
                .strip_prefix(root)
                .map_err(|_| format!("path escapes repository: {}", entry_path.display()))?
                .to_str()
                .ok_or_else(|| "path is not UTF-8".to_owned())?
                .to_owned();
            if matches_declaration(&declaration, &relative) {
                matches.push(relative);
            }
            if file_type.is_dir() {
                pending.push(entry_path);
            }
        }
    }
    matches.sort();
    Ok(matches)
}
