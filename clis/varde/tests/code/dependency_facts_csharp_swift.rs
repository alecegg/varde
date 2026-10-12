//! Dependency-fact end-to-end cases for C# and Swift imports.
//!
//! Harness conventions follow `dependency_policy_gates.rs`: build the fixture
//! index with `varde map build`, then scan the fixture and filter findings by
//! rule id.

use serde_json::Value;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
static NEXT_REPO: AtomicUsize = AtomicUsize::new(0);

struct Repo {
    root: PathBuf,
}
impl Repo {
    fn home(&self) -> PathBuf {
        self.root.with_extension("home")
    }
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "varde-dependency-facts-csharp_swift-{}-{}-{}",
            NEXT_REPO.fetch_add(1, Ordering::Relaxed),
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        Self { root }
    }
    fn write(&self, path: &str, content: &str) {
        let file = self.root.join(path);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, content).unwrap();
    }
    fn command(&self, command: &str, extra: Value) -> (bool, Value) {
        let mut input = extra;
        input["repoRoot"] = serde_json::json!(self.root);
        // Production scans read the watcher-owned index. Keep this fixture's
        // index current explicitly after each source edit.
        if command == "scan" && input["apply"] != true {
            let built = Command::new(env!("CARGO_BIN_EXE_varde"))
                .args(["map", "build", "--repo-root", self.root.to_str().unwrap()])
                .env("HOME", self.home())
                .output()
                .unwrap();
            assert!(
                built.status.success(),
                "{}",
                String::from_utf8_lossy(&built.stdout)
            );
        }
        let command_args: &[&str] = match command {
            "scan" => &["scan"],
            "rules_list" => &["scan", "rules", "list"],
            _ => panic!("unsupported scan command: {command}"),
        };
        let output = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(command_args)
            .args(["--json", &input.to_string()])
            .env("HOME", self.home())
            .env("VARDE_USER_RULES_DIR", self.root.join("empty-user-rules"))
            .output()
            .unwrap();
        let payload = serde_json::from_slice(&output.stdout).unwrap_or_else(|_| {
            panic!(
                "{}\n{}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            )
        });
        (output.status.success(), payload)
    }
    fn scan(&self) -> Value {
        let (_, payload) = self.command("scan", serde_json::json!({}));
        assert_eq!(payload["ok"], true, "{payload}");
        assert!(
            payload["data"]["diagnostics"]
                .as_array()
                .unwrap()
                .is_empty(),
            "{payload}"
        );
        payload
    }
    fn boundary(&self, source: &str, target: &str) {
        self.write(
            ".varde-code/rules/boundary.toml",
            &include_str!(
                "../../../code/crates/varde-code/src/rules/builtin/dependency_boundary.toml"
            )
            .replace(
                "source_prefix = \"\"",
                &format!("source_prefix = {source:?}"),
            )
            .replace(
                "target_prefix = \"\"",
                &format!("target_prefix = {target:?}"),
            ),
        );
    }
}
impl Drop for Repo {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
        let _ = std::fs::remove_dir_all(self.home());
    }
}
fn findings<'a>(payload: &'a Value, id: &str) -> Vec<&'a Value> {
    payload["data"]["findings"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|f| f["rule_id"] == id)
        .collect()
}

const CSPROJ: &str = "<Project Sdk=\"Microsoft.NET.Sdk\" />\n";

fn csharp_project(repo: &Repo, name: &str, body: &str) {
    repo.write(&format!("{name}/{name}.csproj"), CSPROJ);
    repo.write(&format!("{name}/{name}.cs"), body);
}

fn swift_package(repo: &Repo, package: &str, targets: &[(&str, &str)]) {
    let names: Vec<String> = targets
        .iter()
        .map(|(n, _)| format!(".target(name: \"{n}\")"))
        .collect();
    repo.write(
        &format!("{package}/Package.swift"),
        &format!(
            "let package = Package(name: \"P\", targets: [{}])\n",
            names.join(", ")
        ),
    );
    for (name, body) in targets {
        repo.write(&format!("{package}/Sources/{name}/{name}.swift"), body);
    }
}

fn xcode_id(counter: &mut usize) -> String {
    let value = format!("{:024X}", *counter);
    *counter += 1;
    value
}

/// Write an Xcode project whose native targets each own one Swift source in
/// its own directory: `(target name, source directory, file name, body)`.
/// Repeated entries with the same directory share a source directory on
/// purpose, which exercises the ambiguity guard.
fn xcode_project(repo: &Repo, project: &str, targets: &[(&str, &str, &str, &str)]) {
    let mut counter = 0usize;
    let main_group = xcode_id(&mut counter);
    let project_object = xcode_id(&mut counter);

    let mut build_files = String::new();
    let mut file_refs = String::new();
    let mut groups = String::new();
    let mut main_children = String::new();
    let mut native_targets = String::new();
    let mut sources_phases = String::new();
    let mut configurations = String::new();
    let mut configuration_lists = String::new();

    for (name, dir, file, body) in targets {
        let group = xcode_id(&mut counter);
        let file_ref = xcode_id(&mut counter);
        let build_file = xcode_id(&mut counter);
        let phase = xcode_id(&mut counter);
        let target = xcode_id(&mut counter);
        let list = xcode_id(&mut counter);
        let configuration = xcode_id(&mut counter);

        build_files.push_str(&format!(
            "\t\t{build_file} /* {file} in Sources */ = {{isa = PBXBuildFile; fileRef = {file_ref} /* {file} */; }};\n"
        ));
        file_refs.push_str(&format!(
            "\t\t{file_ref} /* {file} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {file:?}; sourceTree = \"<group>\"; }};\n"
        ));
        groups.push_str(&format!(
            "\t\t{group} /* {dir} */ = {{ isa = PBXGroup; children = (\n\t\t\t{file_ref} /* {file} */,\n\t\t); path = {dir:?}; sourceTree = \"<group>\"; }};\n"
        ));
        main_children.push_str(&format!("\t\t\t{group} /* {dir} */,\n"));
        native_targets.push_str(&format!(
            "\t\t{target} /* {name} */ = {{ isa = PBXNativeTarget; buildConfigurationList = {list}; buildPhases = (\n\t\t\t{phase} /* Sources */,\n\t\t); name = {name:?}; productType = \"com.apple.product-type.framework\"; }};\n"
        ));
        sources_phases.push_str(&format!(
            "\t\t{phase} /* Sources */ = {{ isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (\n\t\t\t{build_file} /* {file} in Sources */,\n\t\t); runOnlyForDeploymentPostprocessing = 0; }};\n"
        ));
        configurations.push_str(&format!(
            "\t\t{configuration} /* Debug */ = {{ isa = XCBuildConfiguration; buildSettings = {{ PRODUCT_NAME = \"$(TARGET_NAME:c99extidentifier)\"; }}; name = Debug; }};\n"
        ));
        configuration_lists.push_str(&format!(
            "\t\t{list} /* Build configuration list */ = {{ isa = XCConfigurationList; buildConfigurations = (\n\t\t\t{configuration} /* Debug */,\n\t\t); defaultConfigurationIsVisible = 0; }};\n"
        ));

        repo.write(&format!("{project}/{dir}/{file}"), body);
    }

    let groups = format!(
        "\t\t{main_group} /* Main */ = {{ isa = PBXGroup; children = (\n{main_children}\t\t); sourceTree = \"<group>\"; }};\n{groups}"
    );
    let template = r#"// !$*UTF8*$!
{
	archiveVersion = 1;
	classes = {
	};
	objectVersion = 54;
	objects = {

/* Begin PBXBuildFile section */
%BUILD_FILES%/* End PBXBuildFile section */

/* Begin PBXFileReference section */
%FILE_REFS%/* End PBXFileReference section */

/* Begin PBXGroup section */
%GROUPS%/* End PBXGroup section */

/* Begin PBXNativeTarget section */
%NATIVE_TARGETS%/* End PBXNativeTarget section */

/* Begin PBXProject section */
		%PROJECT_OBJECT% /* Project object */ = { isa = PBXProject; mainGroup = %MAIN_GROUP%; };
/* End PBXProject section */

/* Begin PBXSourcesBuildPhase section */
%SOURCES_PHASES%/* End PBXSourcesBuildPhase section */

/* Begin XCBuildConfiguration section */
%CONFIGURATIONS%/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
%CONFIGURATION_LISTS%/* End XCConfigurationList section */
	};
	rootObject = %PROJECT_OBJECT% /* Project object */;
}
"#;
    let text = template
        .replace("%BUILD_FILES%", &build_files)
        .replace("%FILE_REFS%", &file_refs)
        .replace("%GROUPS%", &groups)
        .replace("%NATIVE_TARGETS%", &native_targets)
        .replace("%PROJECT_OBJECT%", &project_object)
        .replace("%MAIN_GROUP%", &main_group)
        .replace("%SOURCES_PHASES%", &sources_phases)
        .replace("%CONFIGURATIONS%", &configurations)
        .replace("%CONFIGURATION_LISTS%", &configuration_lists);
    repo.write(
        &format!("{project}/{project}.xcodeproj/project.pbxproj"),
        &text,
    );
}

#[test]
fn csharp_cycle_between_projects_is_reported_once() {
    let repo = Repo::new();
    csharp_project(
        &repo,
        "Alpha",
        "using Beta;\nnamespace Alpha;\npublic class A {}\n",
    );
    csharp_project(
        &repo,
        "Beta",
        "using Alpha;\nnamespace Beta;\npublic class B {}\n",
    );
    let payload = repo.scan();
    assert_eq!(findings(&payload, "circular-import").len(), 1, "{payload}");
}

#[test]
fn csharp_valid_external_missing_and_guarded_imports_yield_no_finding() {
    let repo = Repo::new();
    csharp_project(
        &repo,
        "Alpha",
        "using System;\nusing Missing.Lib;\nusing Beta;\nnamespace Alpha;\n",
    );
    csharp_project(&repo, "Beta", "namespace Beta;\n");
    assert!(findings(&repo.scan(), "circular-import").is_empty());
    assert!(findings(&repo.scan(), "unresolved-local-import").is_empty());
    // A guarded, global or static back-reference is not a certified edge.
    for back in [
        "#if NET8\nusing Alpha;\n#endif\n",
        "global using Alpha;\n",
        "using static Alpha.A;\n",
    ] {
        csharp_project(&repo, "Beta", &format!("{back}namespace Beta;\n"));
        assert!(
            findings(&repo.scan(), "circular-import").is_empty(),
            "{back}"
        );
    }
}

#[test]
fn csharp_namespace_spread_over_projects_is_ambiguous() {
    let repo = Repo::new();
    csharp_project(&repo, "Alpha", "using Shared;\nnamespace Alpha;\n");
    csharp_project(&repo, "Beta", "using Alpha;\nnamespace Shared;\n");
    assert_eq!(findings(&repo.scan(), "circular-import").len(), 1);
    csharp_project(&repo, "Gamma", "namespace Shared;\n");
    assert!(findings(&repo.scan(), "circular-import").is_empty());
}

#[test]
fn csharp_dependency_boundary_uses_project_prefixes() {
    let repo = Repo::new();
    csharp_project(&repo, "Core", "using Data;\nnamespace Core;\n");
    csharp_project(&repo, "Data", "namespace Data;\n");
    repo.boundary("Core", "Data");
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["location"]["file"], "Core/Core.cs");
    repo.boundary("Data", "Core");
    assert!(findings(&repo.scan(), "dependency-boundary").is_empty());
}

#[test]
fn swift_cycle_between_targets_is_reported_once() {
    let repo = Repo::new();
    swift_package(
        &repo,
        "Pkg",
        &[("Alpha", "import Beta\n"), ("Beta", "import Alpha\n")],
    );
    let payload = repo.scan();
    assert_eq!(findings(&payload, "circular-import").len(), 1, "{payload}");
}

#[test]
fn swift_valid_framework_missing_and_guarded_imports_yield_no_finding() {
    let repo = Repo::new();
    swift_package(
        &repo,
        "Pkg",
        &[
            ("Alpha", "import Foundation\nimport Missing\nimport Beta\n"),
            ("Beta", "#if canImport(Alpha)\nimport Alpha\n#endif\n"),
        ],
    );
    let payload = repo.scan();
    assert!(
        findings(&payload, "circular-import").is_empty(),
        "{payload}"
    );
    assert!(findings(&payload, "unresolved-local-import").is_empty());
}

#[test]
fn swift_target_name_declared_in_two_packages_is_ambiguous() {
    let repo = Repo::new();
    swift_package(
        &repo,
        "One",
        &[("Alpha", "import Beta\n"), ("Beta", "import Alpha\n")],
    );
    assert_eq!(findings(&repo.scan(), "circular-import").len(), 1);
    swift_package(&repo, "Two", &[("Beta", "\n")]);
    assert!(findings(&repo.scan(), "circular-import").is_empty());
}

#[test]
fn swift_dependency_boundary_uses_target_prefixes() {
    let repo = Repo::new();
    swift_package(&repo, "Pkg", &[("Core", "import Data\n"), ("Data", "\n")]);
    repo.boundary("Pkg/Sources/Core", "Pkg/Sources/Data");
    let payload = repo.scan();
    assert_eq!(
        findings(&payload, "dependency-boundary").len(),
        1,
        "{payload}"
    );
    repo.boundary("Pkg/Sources/Data", "Pkg/Sources/Core");
    assert!(findings(&repo.scan(), "dependency-boundary").is_empty());
}

#[test]
fn swift_xcode_cycle_between_targets_is_reported_once() {
    let repo = Repo::new();
    xcode_project(
        &repo,
        "App",
        &[
            ("Alpha", "Alpha", "Alpha.swift", "import Beta\n"),
            ("Beta", "Beta", "Beta.swift", "import Alpha\n"),
        ],
    );
    let payload = repo.scan();
    assert_eq!(findings(&payload, "circular-import").len(), 1, "{payload}");
}

#[test]
fn swift_xcode_valid_and_external_imports_yield_no_finding() {
    let repo = Repo::new();
    xcode_project(
        &repo,
        "App",
        &[
            (
                "Alpha",
                "Alpha",
                "Alpha.swift",
                "import Beta\nimport Missing\n",
            ),
            ("Beta", "Beta", "Beta.swift", "import Foundation\n"),
        ],
    );
    let payload = repo.scan();
    assert!(
        findings(&payload, "circular-import").is_empty(),
        "{payload}"
    );
    assert!(findings(&payload, "unresolved-local-import").is_empty());
}

#[test]
fn swift_xcode_targets_sharing_a_source_directory_are_ambiguous() {
    let repo = Repo::new();
    xcode_project(
        &repo,
        "App",
        &[
            ("Alpha", "Shared", "Alpha.swift", "import Beta\n"),
            ("Beta", "Beta", "Beta.swift", "import Alpha\n"),
        ],
    );
    assert_eq!(findings(&repo.scan(), "circular-import").len(), 1);
    xcode_project(
        &repo,
        "App",
        &[
            ("Alpha", "Shared", "Alpha.swift", "import Beta\n"),
            ("Beta", "Beta", "Beta.swift", "import Alpha\n"),
            ("AlphaCopy", "Shared", "Alpha.swift", "import Beta\n"),
        ],
    );
    assert!(findings(&repo.scan(), "circular-import").is_empty());
}

#[test]
fn swift_xcode_dependency_boundary_uses_target_directories() {
    let repo = Repo::new();
    xcode_project(
        &repo,
        "App",
        &[
            ("Alpha", "Alpha", "Alpha.swift", "import Beta\n"),
            ("Beta", "Beta", "Beta.swift", "\n"),
        ],
    );
    repo.boundary("App/Alpha", "App/Beta");
    let payload = repo.scan();
    let violations = findings(&payload, "dependency-boundary");
    assert_eq!(violations.len(), 1, "{payload}");
    assert_eq!(violations[0]["location"]["file"], "App/Alpha/Alpha.swift");
    repo.boundary("App/Beta", "App/Alpha");
    assert!(findings(&repo.scan(), "dependency-boundary").is_empty());
}
