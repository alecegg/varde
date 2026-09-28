use std::fs;
use std::path::Path;

#[test]
fn production_sources_never_launch_varde_subprocesses() {
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
        let source = fs::read_to_string(&path).unwrap();
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
