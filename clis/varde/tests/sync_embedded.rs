use std::collections::{BTreeMap, BTreeSet};
use std::ffi::OsStr;
use std::fs;
use std::path::{Path, PathBuf};

use varde::sync::embedded::{agents, retired_names, skills};

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

const AGENT_VARIANTS: [&str; 5] = [
    "claude.md",
    "codex.toml",
    "opencode.md",
    "opencode-v2.md",
    "pi.md",
];

const PRIMARY_AGENT_VARIANTS: [&str; 4] = ["claude.md", "codex.toml", "opencode.md", "pi.md"];

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap()
}

fn is_executable(path: &Path) -> bool {
    #[cfg(unix)]
    {
        fs::metadata(path).unwrap().permissions().mode() & 0o111 != 0
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        false
    }
}

fn skill_names(skill_root: &Path) -> Vec<String> {
    let mut names = fs::read_dir(skill_root)
        .unwrap()
        .map(|entry| entry.unwrap())
        .filter(|entry| entry.file_type().unwrap().is_dir())
        .filter_map(|entry| {
            let name = entry.file_name().to_string_lossy().into_owned();
            (name.starts_with("varde-") && entry.path().join("SKILL.md").is_file()).then_some(name)
        })
        .collect::<Vec<_>>();
    names.sort();
    names
}

fn walk_skill_files(root: &Path, current: &Path, files: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(current).unwrap() {
        let entry = entry.unwrap();
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.starts_with('.') {
            continue;
        }

        let path = entry.path();
        let file_type = entry.file_type().unwrap();
        assert!(
            !file_type.is_symlink(),
            "skill tree contains symlink: {}",
            path.display()
        );

        if file_type.is_dir() {
            if name == "evals" || name == "__pycache__" || name.ends_with("-workspace") {
                continue;
            }
            walk_skill_files(root, &path, files);
        } else if file_type.is_file() && path.extension() != Some(OsStr::new("pyc")) {
            files.push(path.strip_prefix(root).unwrap().to_path_buf());
        }
    }
}

fn assert_no_skill_symlinks(current: &Path) {
    for entry in fs::read_dir(current).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        let file_type = entry.file_type().unwrap();
        assert!(
            !file_type.is_symlink(),
            "skill tree contains symlink: {}",
            path.display()
        );
        if file_type.is_dir() {
            assert_no_skill_symlinks(&path);
        }
    }
}

fn manifest_entries(manifest: &Path) -> BTreeMap<String, BTreeSet<String>> {
    let mut entries = BTreeMap::new();
    for line in fs::read_to_string(manifest).unwrap().lines() {
        let mut fields = line.split_whitespace();
        let Some(relative_path) = fields.next() else {
            continue;
        };
        let skills = fields.map(str::to_owned).collect::<BTreeSet<_>>();
        if !skills.is_empty() {
            entries.insert(relative_path.to_owned(), skills);
        }
    }
    entries
}

fn expected_skill_files(
    skill_root: &Path,
    shared_root: &Path,
    manifest: &Path,
    skill_name: &str,
) -> BTreeMap<String, (Vec<u8>, bool)> {
    let root = skill_root.join(skill_name);
    let mut paths = Vec::new();
    walk_skill_files(&root, &root, &mut paths);

    let mut files = paths
        .into_iter()
        .map(|relative_path| {
            let source = root.join(&relative_path);
            let name = relative_path.to_string_lossy().into_owned();
            (name, (fs::read(&source).unwrap(), is_executable(&source)))
        })
        .collect::<BTreeMap<_, _>>();

    for (relative_path, skills) in manifest_entries(manifest) {
        if skills.contains(skill_name) {
            let source = shared_root.join(&relative_path);
            files.insert(
                relative_path,
                (fs::read(&source).unwrap(), is_executable(&source)),
            );
        }
    }
    files
}

#[test]
fn embedded_skills_match_filtered_trees_manifest_files_and_modes() {
    let root = repo_root();
    let skill_root = root.join("skills");
    let shared_root = skill_root.join("shared");
    let manifest = shared_root.join("MANIFEST");
    let expected_names = skill_names(&skill_root);
    let embedded = skills();
    let actual_names = embedded
        .iter()
        .map(|skill| skill.name.to_owned())
        .collect::<Vec<_>>();

    assert_eq!(actual_names, expected_names);

    for skill in embedded {
        assert_no_skill_symlinks(&skill_root.join(skill.name));
        let expected = expected_skill_files(&skill_root, &shared_root, &manifest, skill.name);
        let actual = skill
            .files
            .iter()
            .map(|file| (file.relative_path.to_owned(), file.bytes))
            .collect::<BTreeMap<_, _>>();
        let expected_bytes = expected
            .iter()
            .map(|(path, (bytes, _))| (path.clone(), bytes.as_slice()))
            .collect::<BTreeMap<_, _>>();

        assert_eq!(actual, expected_bytes, "skill {} file contents", skill.name);

        for file in skill.files {
            assert_eq!(
                file.executable, expected[file.relative_path].1,
                "skill {} executable mode for {}",
                skill.name, file.relative_path
            );
            assert!(!file.relative_path.split('/').any(|part| {
                part.starts_with('.')
                    || part == "evals"
                    || part == "__pycache__"
                    || part.ends_with("-workspace")
            }));
            assert!(!file.relative_path.ends_with(".pyc"));
        }
    }
}

#[test]
fn embedded_agents_match_all_committed_variants() {
    let root = repo_root();
    let agent_root = root.join("agents");
    let mut expected_names = Vec::new();
    let mut expected_variants = BTreeMap::new();

    for entry in fs::read_dir(&agent_root).unwrap() {
        let entry = entry.unwrap();
        if !entry.file_type().unwrap().is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().into_owned();
        if !PRIMARY_AGENT_VARIANTS
            .iter()
            .any(|variant| entry.path().join(variant).is_file())
        {
            continue;
        }
        expected_names.push(name.clone());
        let variants = AGENT_VARIANTS
            .iter()
            .filter_map(|variant| {
                let path = entry.path().join(variant);
                path.is_file()
                    .then(|| ((*variant).to_owned(), fs::read(path).unwrap()))
            })
            .collect::<BTreeMap<_, _>>();
        expected_variants.insert(name, variants);
    }
    expected_names.sort();

    let actual = agents();
    let actual_names = actual
        .iter()
        .map(|agent| agent.name.to_owned())
        .collect::<Vec<_>>();
    assert_eq!(actual_names, expected_names);
    for agent in actual {
        let variants = agent
            .variants
            .iter()
            .map(|variant| (variant.file_name.to_owned(), variant.bytes))
            .collect::<BTreeMap<_, _>>();
        let expected = &expected_variants[agent.name];
        let expected_bytes = expected
            .iter()
            .map(|(name, bytes)| (name.clone(), bytes.as_slice()))
            .collect::<BTreeMap<_, _>>();
        assert_eq!(variants, expected_bytes, "agent {} variants", agent.name);
    }

    for required in [
        "varde-builder",
        "varde-explorer",
        "varde-planner",
        "varde-reviewer",
    ] {
        assert!(actual_names.iter().any(|name| name == required));
    }
}

#[test]
fn embedded_retired_names_match_catalogue() {
    let contents = fs::read_to_string(repo_root().join("skills/RETIRED")).unwrap();
    let expected = contents
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect::<Vec<_>>();
    assert_eq!(retired_names(), expected);
}
