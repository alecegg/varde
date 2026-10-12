#![allow(dead_code)]

use std::path::{Path, PathBuf};

use varde_code::extract;
use varde_code::model::{Entity, ExtractOutput, FileMeta, Symbol};
use varde_code::parse::{language_for_path, parse_source};
use varde_code::{persist, resolve};

const FIXTURES: &str = "resolve_fixtures";

pub fn fixture_path(rel: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join(FIXTURES)
        .join(rel)
}

pub struct IndexedFixture {
    pub _temp: tempfile::TempDir,
    pub root: PathBuf,
    pub db: PathBuf,
    pub files: Vec<String>,
    pub entities: Vec<Entity>,
    pub symbols: Vec<Symbol>,
    pub graph: resolve::ResolvedGraph,
}

/// Copy fixture sources into a temporary repository, index and persist them.
pub fn index_and_persist(language: &str, tag: &str, sources: Vec<(String, String)>) -> IndexedFixture {
    let temp = tempfile::tempdir().expect("temporary fixture repository");
    let root = temp.path().to_path_buf();
    std::fs::create_dir_all(root.join(".git")).expect("create fixture index directory");
    let mut files = Vec::new();
    let mut entities = Vec::new();
    let mut symbols = Vec::new();
    for (relative, source) in sources {
        let target = root.join(&relative);
        std::fs::create_dir_all(target.parent().expect("fixture parent"))
            .expect("create fixture source directory");
        std::fs::write(&target, &source).expect("write fixture source");
        let grammar = language_for_path(&target).unwrap_or_else(|| {
            panic!("{language}/{tag}: unsupported fixture path {relative}")
        });
        let extracted = extract::extract(&parse_source(&grammar, &source), files.len() as u32);
        entities.extend(extracted.entities);
        symbols.extend(extracted.symbols);
        files.push(target.to_string_lossy().into_owned());
    }
    let graph = resolve::resolve(&entities, &symbols, &files).expect("resolve fixture");
    let file_meta = files
        .iter()
        .map(|file| {
            let state = varde_code::scan::list_source_files(file)
                .expect("fixture metadata")
                .remove(0);
            FileMeta {
                mtime: state.mtime,
                size: state.size,
                content_hash: state.content_hash.unwrap_or_default(),
            }
        })
        .collect();
    let output = ExtractOutput {
        entities: entities.clone(),
        symbols: symbols.clone(),
        diagnostics: vec![],
        files: files.clone(),
        file_meta,
    };
    let db = root.join(".git/index.db");
    persist::persist(&db, &[output], &graph, &root).expect("persist fixture");
    IndexedFixture { _temp: temp, root, db, files, entities, symbols, graph }
}

/// Parse and extract every supported source file under a fixture directory.
pub fn load_fixture_project(rel: &str) -> (Vec<Entity>, Vec<Symbol>, Vec<String>) {
    let root = fixture_path(rel);
    let mut paths = Vec::new();
    collect_source_files(&root, &mut paths);
    paths.sort();

    let files: Vec<String> = paths
        .iter()
        .map(|path| path.to_string_lossy().into_owned())
        .collect();
    let mut entities = Vec::new();
    let mut symbols = Vec::new();
    for (file_id, path) in paths.iter().enumerate() {
        let source = std::fs::read_to_string(path).expect("read fixture");
        let language = language_for_path(path).expect("supported fixture language");
        let parsed = parse_source(&language, &source);
        let result = extract::extract(&parsed, file_id as u32);
        entities.extend(result.entities);
        symbols.extend(result.symbols);
    }
    (entities, symbols, files)
}

fn collect_source_files(directory: &Path, paths: &mut Vec<PathBuf>) {
    for entry in std::fs::read_dir(directory).expect("resolve fixture dir exists") {
        let path = entry.expect("read fixture directory entry").path();
        if path.is_dir() {
            collect_source_files(&path, paths);
        } else if path.is_file() {
            paths.push(path);
        }
    }
}

mod find_pattern_a;
mod find_pattern_b;
mod nav_entrypoints_a;
mod nav_entrypoints_b;
mod query_symbols_a;
mod query_symbols_b;
mod resolve_a1;
mod resolve_a2;
mod resolve_b1;
mod resolve_b2;
mod resolve_c;
mod sql_boundary;
mod sql_circular;
mod sql_unresolved;
