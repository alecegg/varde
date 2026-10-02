use std::fs;
use std::path::Path;

#[test]
fn production_sources_only_launch_the_scheduler_code_provider() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut files = Vec::new();
    collect_rust_files(&root, &mut files);
    assert!(!files.is_empty());

    let forbidden = [
        "Command::new(\"varde-",
        "Command::new('varde-",
        ".arg(\"varde-",
        ".arg('varde-",
    ];
    for path in files {
        let mut source = fs::read_to_string(&path).unwrap();
        if path == root.join("execution_wave_tools.rs") {
            // The scheduler queries the installed code provider; every other
            // Varde subprocess remains forbidden, including in this module.
            let provider =
                r#"Command::new("varde-code").args(["blast_radius", "--json", &payload])"#;
            assert_eq!(source.matches(provider).count(), 1);
            source = source.replacen(provider, "approved_code_provider()", 1);
        }
        for pattern in forbidden {
            assert!(
                !source.contains(pattern),
                "{} contains forbidden subprocess pattern {pattern}",
                path.display()
            );
        }
    }
}

fn collect_rust_files(directory: &Path, files: &mut Vec<std::path::PathBuf>) {
    for entry in fs::read_dir(directory).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            collect_rust_files(&path, files);
        } else if path.extension().is_some_and(|extension| extension == "rs") {
            files.push(path);
        }
    }
}
