use std::collections::BTreeMap;
use std::env;
use std::fmt::Write as _;
use std::fs;
use std::path::{Component, Path, PathBuf};

const PRIMARY_AGENT_VARIANTS: [&str; 4] = ["claude.md", "codex.toml", "opencode.md", "pi.md"];
const AGENT_VARIANTS: [&str; 5] = [
    "claude.md",
    "codex.toml",
    "opencode.md",
    "opencode-v2.md",
    "pi.md",
];

struct SourceFile {
    path: PathBuf,
    executable: bool,
}

fn directory_entries(path: &Path) -> Vec<fs::DirEntry> {
    let mut entries = fs::read_dir(path)
        .unwrap_or_else(|error| panic!("{}: {error}", path.display()))
        .map(|entry| entry.unwrap_or_else(|error| panic!("{}: {error}", path.display())))
        .collect::<Vec<_>>();
    entries.sort_by_key(fs::DirEntry::file_name);
    entries
}

fn emit_watches(path: &Path) {
    println!("cargo:rerun-if-changed={}", path.display());
    let metadata =
        fs::symlink_metadata(path).unwrap_or_else(|error| panic!("{}: {error}", path.display()));
    if metadata.file_type().is_dir() {
        for entry in directory_entries(path) {
            emit_watches(&entry.path());
        }
    }
}

fn slash_path(path: &Path) -> String {
    path.components()
        .map(|component| component.as_os_str().to_string_lossy())
        .collect::<Vec<_>>()
        .join("/")
}

fn is_skipped_directory(name: &str) -> bool {
    name == "evals" || name == "__pycache__" || name.ends_with("-workspace")
}

fn reject_skill_symlinks(current: &Path) {
    for entry in directory_entries(current) {
        let path = entry.path();
        let file_type = entry
            .file_type()
            .unwrap_or_else(|error| panic!("{}: {error}", path.display()));
        if file_type.is_symlink() {
            panic!("Symlink in skill package: {}", path.display());
        }
        if file_type.is_dir() {
            reject_skill_symlinks(&path);
        }
    }
}

fn executable(path: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::metadata(path)
            .unwrap_or_else(|error| panic!("{}: {error}", path.display()))
            .permissions()
            .mode()
            & 0o111
            != 0
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        false
    }
}

fn source_file(path: PathBuf) -> SourceFile {
    let metadata =
        fs::symlink_metadata(&path).unwrap_or_else(|error| panic!("{}: {error}", path.display()));
    if metadata.file_type().is_symlink() {
        panic!("Symlink in skill package: {}", path.display());
    }
    if !metadata.is_file() {
        panic!("Unsupported skill entry: {}", path.display());
    }
    SourceFile {
        executable: executable(&path),
        path,
    }
}

fn walk_skill(skill_root: &Path, current: &Path, files: &mut BTreeMap<String, SourceFile>) {
    for entry in directory_entries(current) {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.starts_with('.') {
            continue;
        }

        let file_type = entry
            .file_type()
            .unwrap_or_else(|error| panic!("{}: {error}", path.display()));
        if file_type.is_dir() {
            if !is_skipped_directory(&name) {
                walk_skill(skill_root, &path, files);
            }
        } else if file_type.is_symlink() {
            panic!("Symlink in skill package: {}", path.display());
        } else if file_type.is_file() {
            if name.ends_with(".pyc") {
                continue;
            }
            let relative_path = slash_path(path.strip_prefix(skill_root).unwrap());
            files.insert(relative_path, source_file(path));
        } else {
            panic!("Unsupported skill entry: {}", path.display());
        }
    }
}

fn skills(skill_root: &Path, shared_root: &Path) -> Vec<(String, BTreeMap<String, SourceFile>)> {
    let manifest = shared_root.join("MANIFEST");
    let manifest_text = fs::read_to_string(&manifest)
        .unwrap_or_else(|error| panic!("{}: {error}", manifest.display()));
    let mut skills = Vec::new();

    for entry in directory_entries(skill_root) {
        let name = entry.file_name().to_string_lossy().into_owned();
        if !name.starts_with("varde-") {
            continue;
        }
        let directory_type = entry
            .file_type()
            .unwrap_or_else(|error| panic!("{}: {error}", entry.path().display()));
        let path = entry.path();
        if directory_type.is_symlink() && path.join("SKILL.md").is_file() {
            panic!("Symlink in skill package: {}", path.display());
        }
        if !directory_type.is_dir() || !path.join("SKILL.md").is_file() {
            continue;
        }

        let mut files = BTreeMap::new();
        reject_skill_symlinks(&path);
        walk_skill(&path, &path, &mut files);

        for (line_number, line) in manifest_text.lines().enumerate() {
            let mut fields = line.split_whitespace();
            let Some(relative_path) = fields.next() else {
                continue;
            };
            let listed_skills = fields.collect::<Vec<_>>();
            if listed_skills.is_empty() {
                panic!(
                    "{}:{}: expected a path and at least one skill",
                    manifest.display(),
                    line_number + 1
                );
            }
            if !listed_skills.contains(&name.as_str()) {
                continue;
            }

            let relative_path = Path::new(relative_path);
            if relative_path.is_absolute()
                || relative_path.components().any(|component| {
                    matches!(
                        component,
                        Component::ParentDir | Component::RootDir | Component::Prefix(_)
                    )
                })
            {
                panic!(
                    "{}:{}: shared path must stay under shared/",
                    manifest.display(),
                    line_number + 1
                );
            }
            let relative_name = slash_path(relative_path);
            let source = source_file(shared_root.join(relative_path));
            files.insert(relative_name, source);
        }

        skills.push((name, files));
    }
    skills
}

fn agents(agent_root: &Path) -> Vec<(String, Vec<(String, PathBuf)>)> {
    let mut agents = Vec::new();
    for entry in directory_entries(agent_root) {
        if !entry
            .file_type()
            .unwrap_or_else(|error| panic!("{}: {error}", entry.path().display()))
            .is_dir()
        {
            continue;
        }
        let name = entry.file_name().to_string_lossy().into_owned();
        let directory = entry.path();
        let has_primary_variant = PRIMARY_AGENT_VARIANTS
            .iter()
            .any(|variant| directory.join(variant).is_file());
        if !has_primary_variant {
            continue;
        }

        let variants = AGENT_VARIANTS
            .iter()
            .filter_map(|variant| {
                let path = directory.join(variant);
                path.is_file().then(|| ((*variant).to_owned(), path))
            })
            .collect();
        agents.push((name, variants));
    }
    agents
}

fn rust_string(value: &str) -> String {
    format!("{value:?}")
}

fn main() {
    let manifest_dir =
        PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let repository_root = manifest_dir
        .join("../..")
        .canonicalize()
        .expect("repository root");
    let skill_root = repository_root.join("skills");
    let shared_root = skill_root.join("shared");
    let agent_root = repository_root.join("agents");
    emit_watches(&skill_root);
    emit_watches(&agent_root);

    let skills = skills(&skill_root, &shared_root);
    let agents = agents(&agent_root);
    let retired_path = skill_root.join("RETIRED");
    let retired_names = fs::read_to_string(&retired_path)
        .unwrap_or_else(|error| panic!("{}: {error}", retired_path.display()))
        .lines()
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let presets_path = skill_root.join("presets.json");

    let mut generated = String::from("// Generated by clis/varde/build.rs.\n");
    writeln!(generated, "static EMBEDDED_SKILLS: &[Skill] = &[").unwrap();
    for (name, files) in skills {
        writeln!(
            generated,
            "    Skill {{ name: {}, files: &[",
            rust_string(&name)
        )
        .unwrap();
        for (relative_path, source) in files {
            writeln!(
                generated,
                "        SkillFile {{ relative_path: {}, bytes: include_bytes!({}), executable: {} }},",
                rust_string(&relative_path),
                rust_string(&source.path.display().to_string()),
                source.executable
            )
            .unwrap();
        }
        generated.push_str("    ] },\n");
    }
    generated.push_str("];\n\n");

    writeln!(generated, "static EMBEDDED_AGENTS: &[Agent] = &[").unwrap();
    for (name, variants) in agents {
        writeln!(
            generated,
            "    Agent {{ name: {}, variants: &[",
            rust_string(&name)
        )
        .unwrap();
        for (file_name, path) in variants {
            writeln!(
                generated,
                "        AgentVariant {{ file_name: {}, bytes: include_bytes!({}) }},",
                rust_string(&file_name),
                rust_string(&path.display().to_string())
            )
            .unwrap();
        }
        generated.push_str("    ] },\n");
    }
    generated.push_str("];\n\nstatic RETIRED_NAMES: &[&str] = &[\n");
    for name in retired_names {
        writeln!(generated, "    {},", rust_string(&name)).unwrap();
    }
    generated.push_str("];\n");

    let out_dir = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR"));
    fs::copy(&presets_path, out_dir.join("presets.json"))
        .unwrap_or_else(|error| panic!("{}: {error}", presets_path.display()));
    fs::write(out_dir.join("embedded.rs"), generated).expect("write generated embedded.rs");
}
