//! Source-aware dependency facts for enforceable SQL rules.
//!
//! The persisted graph deliberately contains approximate resolution for some
//! languages.  Blocking policies need a smaller contract: relative imports
//! are certified only when the physical and indexed targets agree exactly,
//! while Go uses the already module-aware persisted edges.  Facts live in a
//! TEMP table so a scan never changes the index schema.

use rusqlite::{Connection, params};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

const IMPORT_KIND: i64 = 1;
const TYPE_ONLY: &str = "type_only";

/// Build the scan-local dependency facts table.
///
/// The connection may be read-only for the main database. SQLite permits
/// writes to TEMP tables on such a connection. All database and filesystem
/// failures are returned so callers can fail closed.
pub fn prepare(conn: &Connection, repo_root: &Path) -> Result<(), String> {
    let root = repository_root(repo_root)?;
    let files = load_files(conn, &root)?;
    let indexed = indexed_paths(&files);
    let imports = load_imports(conn, &files)?;
    let edges = load_resolved_import_edges(conn)?;
    let facts = build_facts(&root, &files, &indexed, &imports, &edges)?;
    write_facts(conn, facts)
}

fn repository_root(repo_root: &Path) -> Result<PathBuf, String> {
    let root = std::path::absolute(repo_root)
        .map_err(|error| format!("resolve repository root: {error}"))?;
    let metadata =
        std::fs::metadata(&root).map_err(|error| format!("stat repository root: {error}"))?;
    if metadata.is_dir() {
        Ok(root)
    } else {
        Err(format!(
            "repository root is not a directory: {}",
            root.display()
        ))
    }
}

fn build_facts(
    root: &Path,
    files: &[FileRow],
    indexed: &HashMap<String, Vec<i64>>,
    imports: &[ImportRow],
    edges: &[EdgeRow],
) -> Result<Vec<Fact>, String> {
    let mut facts = build_go_facts(files, imports, edges)?;
    facts.extend(build_relative_facts(root, files, indexed, imports)?);
    facts.sort_by(fact_order);
    deduplicate_facts(&mut facts);
    Ok(facts)
}

fn deduplicate_facts(facts: &mut Vec<Fact>) {
    facts.dedup_by(|left, right| {
        left.from_file_id == right.from_file_id
            && left.source_entity_id == right.source_entity_id
            && left.to_unit == right.to_unit
            && left.certainty == right.certainty
    });
}

fn write_facts(conn: &Connection, facts: Vec<Fact>) -> Result<(), String> {
    conn.execute_batch(
        "DROP TABLE IF EXISTS temp.dependency_facts;
         CREATE TEMP TABLE dependency_facts (
             from_file_id INTEGER NOT NULL,
             from_unit TEXT NOT NULL,
             to_file_id INTEGER,
             to_unit TEXT,
             kind INTEGER NOT NULL,
             certainty TEXT NOT NULL,
             source_entity_id INTEGER NOT NULL,
             specifier TEXT NOT NULL
         );",
    )
    .map_err(|error| format!("create temporary dependency_facts table: {error}"))?;

    let mut statement = conn
        .prepare(
            "INSERT INTO temp.dependency_facts
             (from_file_id, from_unit, to_file_id, to_unit, kind, certainty,
              source_entity_id, specifier)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        )
        .map_err(|error| format!("prepare dependency fact insert: {error}"))?;
    for fact in facts {
        statement
            .execute(params![
                fact.from_file_id,
                fact.from_unit,
                fact.to_file_id,
                fact.to_unit,
                fact.kind,
                fact.certainty,
                fact.source_entity_id,
                fact.specifier,
            ])
            .map_err(|error| format!("insert dependency fact: {error}"))?;
    }
    Ok(())
}

#[derive(Debug, Clone)]
struct FileRow {
    id: i64,
    path: String,
    relative: String,
    physical: PathBuf,
    is_test: bool,
    is_tooling: bool,
}

#[derive(Debug, Clone)]
struct ImportRow {
    id: i64,
    file_id: i64,
    specifier: String,
    type_only: bool,
}

#[derive(Debug, Clone)]
struct EdgeRow {
    from_file_id: i64,
    from_entity_id: Option<i64>,
    to_file_id: Option<i64>,
    resolved: bool,
}

#[derive(Debug, Clone)]
struct Fact {
    from_file_id: i64,
    from_unit: String,
    to_file_id: Option<i64>,
    to_unit: Option<String>,
    kind: i64,
    certainty: &'static str,
    source_entity_id: i64,
    specifier: String,
}

fn load_files(conn: &Connection, root: &Path) -> Result<Vec<FileRow>, String> {
    let mut statement = conn
        .prepare(
            "SELECT id, path, is_test_path, is_tooling_path
             FROM files ORDER BY id",
        )
        .map_err(|error| format!("load indexed files: {error}"))?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, i64>(3)?,
            ))
        })
        .map_err(|error| format!("read indexed files: {error}"))?;

    let mut files = Vec::new();
    for row in rows {
        let (id, path, is_test, is_tooling) =
            row.map_err(|error| format!("read indexed file row: {error}"))?;
        let Some((relative, physical)) = repository_path(root, Path::new(&path))? else {
            continue;
        };
        files.push(FileRow {
            id,
            path,
            relative,
            physical,
            is_test: is_test != 0,
            is_tooling: is_tooling != 0,
        });
    }
    Ok(files)
}

fn load_imports(conn: &Connection, files: &[FileRow]) -> Result<Vec<ImportRow>, String> {
    let mut statement = conn
        .prepare(
            "SELECT id, file_id, name, body_shape
             FROM entities WHERE kind = 9 ORDER BY id",
        )
        .map_err(|error| format!("load import entities: {error}"))?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<String>>(3)?,
            ))
        })
        .map_err(|error| format!("read import entities: {error}"))?;

    let known_files: HashSet<i64> = files.iter().map(|file| file.id).collect();
    let mut imports = Vec::new();
    for row in rows {
        let (id, file_id, specifier, body_shape) =
            row.map_err(|error| format!("read import entity row: {error}"))?;
        if known_files.contains(&file_id) {
            imports.push(ImportRow {
                id,
                file_id,
                specifier,
                type_only: body_shape.as_deref() == Some(TYPE_ONLY),
            });
        }
    }
    Ok(imports)
}

fn load_resolved_import_edges(conn: &Connection) -> Result<Vec<EdgeRow>, String> {
    let mut statement = conn
        .prepare(
            "SELECT from_file_id, from_entity_id, to_file_id, resolved
             FROM resolved_edges WHERE kind = ?1 ORDER BY id",
        )
        .map_err(|error| format!("load resolved import edges: {error}"))?;
    let rows = statement
        .query_map([IMPORT_KIND], |row| {
            Ok(EdgeRow {
                from_file_id: row.get(0)?,
                from_entity_id: row.get(1)?,
                to_file_id: row.get(2)?,
                resolved: row.get::<_, i64>(3)? != 0,
            })
        })
        .map_err(|error| format!("read resolved import edges: {error}"))?;
    rows.map(|row| row.map_err(|error| format!("read resolved import edge row: {error}")))
        .collect()
}

fn indexed_paths(files: &[FileRow]) -> HashMap<String, Vec<i64>> {
    let mut indexed = HashMap::new();
    for file in files {
        indexed
            .entry(file.relative.clone())
            .or_insert_with(Vec::new)
            .push(file.id);
    }
    indexed
}

fn build_relative_facts(
    root: &Path,
    files: &[FileRow],
    indexed: &HashMap<String, Vec<i64>>,
    imports: &[ImportRow],
) -> Result<Vec<Fact>, String> {
    let by_id: HashMap<i64, &FileRow> = files.iter().map(|file| (file.id, file)).collect();
    let mut facts = Vec::new();
    for import in imports {
        if let Some(fact) = relative_fact(root, &by_id, indexed, import)? {
            facts.push(fact);
        }
    }
    Ok(facts)
}

fn relative_fact(
    root: &Path,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
    import: &ImportRow,
) -> Result<Option<Fact>, String> {
    let Some(source) = by_id.get(&import.file_id) else {
        return Ok(None);
    };
    if !relative_import_allowed(source, import) {
        return Ok(None);
    }
    let Some(raw_spec) = clean_relative_spec(import) else {
        return Ok(None);
    };
    let Some(base) = relative_base(source, &raw_spec) else {
        return Ok(None);
    };
    let source_lang = crate::parse::language_for_path(Path::new(&source.path));
    if !supports_source_relative(source_lang) || has_loader_or_query(&raw_spec) {
        return Ok(None);
    }
    if extensionless_loader_override(root, &base, &raw_spec)? {
        return Ok(None);
    }
    let candidates = candidate_paths(&base, source_lang, &raw_spec);
    if candidates.is_empty() {
        return Ok(None);
    }
    let targets = physical_targets(root, candidates)?;
    Ok(certified_or_missing(
        by_id,
        indexed,
        source,
        import,
        source_lang,
        targets,
        &raw_spec,
    ))
}

fn relative_import_allowed(source: &FileRow, import: &ImportRow) -> bool {
    !import.type_only
        && !source.is_test
        && !source.is_tooling
        && !is_go(source)
        && is_relative_spec(&import.specifier)
}

fn clean_relative_spec(import: &ImportRow) -> Option<String> {
    clean_specifier(&import.specifier)
}

fn relative_base(source: &FileRow, raw_spec: &str) -> Option<String> {
    resolve_relative_path(&source.relative, raw_spec)
}

fn extensionless_loader_override(root: &Path, base: &str, raw_spec: &str) -> Result<bool, String> {
    if Path::new(raw_spec).extension().is_some() {
        return Ok(false);
    }
    let exact = root.join(base);
    Ok(
        metadata_if_exists(&exact)?.is_some_and(|metadata| metadata.is_file())
            || metadata_if_exists(&exact.join("package.json"))?.is_some(),
    )
}

#[derive(Debug, Default)]
struct PhysicalTargets {
    paths: Vec<(String, PathBuf)>,
    existing_path: bool,
}

fn physical_targets(root: &Path, candidates: Vec<String>) -> Result<PhysicalTargets, String> {
    let mut targets = PhysicalTargets::default();
    for candidate in candidates {
        let absolute = root.join(candidate.replace('/', std::path::MAIN_SEPARATOR_STR));
        match metadata_if_exists(&absolute)? {
            Some(metadata) if metadata.is_file() => {
                targets.existing_path = true;
                targets.paths.push((candidate, absolute));
            }
            Some(_) => targets.existing_path = true,
            None => {}
        }
    }
    targets.paths = dedup_physical(targets.paths);
    Ok(targets)
}

fn certified_or_missing(
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
    source: &FileRow,
    import: &ImportRow,
    source_lang: Option<ast_grep_language::SupportLang>,
    targets: PhysicalTargets,
    raw_spec: &str,
) -> Option<Fact> {
    let indexed_targets = indexed_targets(indexed, &targets.paths);
    if targets.paths.len() == 1 && indexed_targets.len() == 1 {
        return certified_fact(by_id, source, import, indexed_targets[0].1);
    }
    if targets.paths.is_empty()
        && !targets.existing_path
        && is_missing_candidate(raw_spec, source_lang)
    {
        return Some(missing_fact(source, import));
    }
    None
}

fn indexed_targets<'a>(
    indexed: &'a HashMap<String, Vec<i64>>,
    physical: &'a [(String, PathBuf)],
) -> Vec<(&'a str, i64)> {
    physical
        .iter()
        .flat_map(|(path, _)| {
            indexed
                .get(path)
                .into_iter()
                .flatten()
                .map(move |id| (path.as_str(), *id))
        })
        .collect()
}

fn certified_fact(
    by_id: &HashMap<i64, &FileRow>,
    source: &FileRow,
    import: &ImportRow,
    target_id: i64,
) -> Option<Fact> {
    let target = by_id.get(&target_id)?;
    if target.is_test || target.is_tooling || target.id == source.id {
        return None;
    }
    let from_unit = source.relative.clone();
    let to_unit = target.relative.clone();
    (from_unit != to_unit).then(|| Fact {
        from_file_id: source.id,
        from_unit,
        to_file_id: Some(target.id),
        to_unit: Some(to_unit),
        kind: IMPORT_KIND,
        certainty: "certified",
        source_entity_id: import.id,
        specifier: import.specifier.clone(),
    })
}

fn missing_fact(source: &FileRow, import: &ImportRow) -> Fact {
    Fact {
        from_file_id: source.id,
        from_unit: source.relative.clone(),
        to_file_id: None,
        to_unit: None,
        kind: IMPORT_KIND,
        certainty: "missing",
        source_entity_id: import.id,
        specifier: import.specifier.clone(),
    }
}

fn metadata_if_exists(path: &Path) -> Result<Option<std::fs::Metadata>, String> {
    match std::fs::metadata(path) {
        Ok(metadata) => Ok(Some(metadata)),
        Err(error)
            if matches!(
                error.kind(),
                std::io::ErrorKind::NotFound | std::io::ErrorKind::NotADirectory
            ) =>
        {
            Ok(None)
        }
        Err(error) => Err(format!(
            "stat dependency target {}: {error}",
            path.display()
        )),
    }
}

fn build_go_facts(
    files: &[FileRow],
    imports: &[ImportRow],
    edges: &[EdgeRow],
) -> Result<Vec<Fact>, String> {
    let by_id: HashMap<i64, &FileRow> = files.iter().map(|file| (file.id, file)).collect();
    let import_by_id: HashMap<i64, &ImportRow> =
        imports.iter().map(|import| (import.id, import)).collect();
    let grouped = group_go_targets(&by_id, &import_by_id, edges);
    let mut facts = Vec::new();
    for (key, targets) in grouped {
        if let Some(fact) = go_fact(&by_id, &import_by_id, key, targets)? {
            facts.push(fact);
        }
    }
    Ok(facts)
}

fn group_go_targets<'a>(
    by_id: &HashMap<i64, &'a FileRow>,
    import_by_id: &HashMap<i64, &'a ImportRow>,
    edges: &[EdgeRow],
) -> HashMap<(i64, i64, String), Vec<&'a FileRow>> {
    let mut grouped = HashMap::new();
    for edge in edges {
        let Some((key, target)) = go_edge_target(by_id, import_by_id, edge) else {
            continue;
        };
        grouped.entry(key).or_insert_with(Vec::new).push(target);
    }
    grouped
}

fn go_edge_target<'a>(
    by_id: &HashMap<i64, &'a FileRow>,
    import_by_id: &HashMap<i64, &'a ImportRow>,
    edge: &EdgeRow,
) -> Option<((i64, i64, String), &'a FileRow)> {
    if !edge.resolved {
        return None;
    }
    let source = by_id.get(&edge.from_file_id)?;
    if !is_go(source) || source.is_test || source.is_tooling {
        return None;
    }
    let entity_id = edge.from_entity_id?;
    let import = import_by_id.get(&entity_id)?;
    if import.type_only {
        return None;
    }
    let target = by_id.get(&edge.to_file_id?)?;
    if !is_go(target) || target.is_test || target.is_tooling {
        return None;
    }
    let to_unit = package_unit(&target.relative)?;
    Some(((source.id, entity_id, to_unit), *target))
}

fn go_fact(
    by_id: &HashMap<i64, &FileRow>,
    import_by_id: &HashMap<i64, &ImportRow>,
    (from_id, source_entity_id, to_unit): (i64, i64, String),
    mut targets: Vec<&FileRow>,
) -> Result<Option<Fact>, String> {
    let Some(source) = by_id.get(&from_id) else {
        return Ok(None);
    };
    let Some(from_unit) = package_unit(&source.relative) else {
        return Ok(None);
    };
    if from_unit == to_unit {
        return Ok(None);
    }
    targets.sort_by(|left, right| left.relative.cmp(&right.relative));
    targets.dedup_by_key(|target| target.id);
    let Some(target) = targets.first() else {
        return Ok(None);
    };
    if !check_go_target(target)? {
        return Ok(None);
    }
    let Some(import) = import_by_id.get(&source_entity_id) else {
        return Ok(None);
    };
    Ok(Some(Fact {
        from_file_id: source.id,
        from_unit,
        to_file_id: Some(target.id),
        to_unit: Some(to_unit),
        kind: IMPORT_KIND,
        certainty: "certified",
        source_entity_id,
        specifier: import.specifier.clone(),
    }))
}

fn check_go_target(target: &FileRow) -> Result<bool, String> {
    match std::fs::metadata(&target.physical) {
        Ok(metadata) if metadata.is_file() => Ok(true),
        Ok(_) => Ok(false),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(format!(
            "stat Go dependency target {}: {error}",
            target.physical.display()
        )),
    }
}

fn is_go(file: &FileRow) -> bool {
    crate::parse::language_for_path(Path::new(&file.path))
        == Some(ast_grep_language::SupportLang::Go)
}

fn supports_source_relative(lang: Option<ast_grep_language::SupportLang>) -> bool {
    matches!(
        lang,
        Some(ast_grep_language::SupportLang::JavaScript)
            | Some(ast_grep_language::SupportLang::TypeScript)
            | Some(ast_grep_language::SupportLang::Tsx)
            | Some(ast_grep_language::SupportLang::Dart)
            | Some(ast_grep_language::SupportLang::Solidity)
    )
}

fn package_unit(path: &str) -> Option<String> {
    let parent = Path::new(path).parent().unwrap_or_else(|| Path::new(""));
    let unit = parent
        .to_string_lossy()
        .replace(std::path::MAIN_SEPARATOR, "/");
    Some(if unit.is_empty() {
        ".".to_string()
    } else {
        unit
    })
}

fn fact_order(left: &Fact, right: &Fact) -> std::cmp::Ordering {
    left.from_unit
        .cmp(&right.from_unit)
        .then_with(|| left.to_unit.cmp(&right.to_unit))
        .then_with(|| left.source_entity_id.cmp(&right.source_entity_id))
        .then_with(|| left.specifier.cmp(&right.specifier))
}

fn repository_path(root: &Path, stored: &Path) -> Result<Option<(String, PathBuf)>, String> {
    let absolute = if stored.is_absolute() {
        lexical_normalize(stored)
    } else {
        lexical_normalize(&root.join(stored))
    };
    let relative = match absolute.strip_prefix(root) {
        Ok(relative) => relative.to_path_buf(),
        Err(_) => {
            let canonical_root = std::fs::canonicalize(root)
                .map_err(|error| format!("canonicalize repository root: {error}"))?;
            let Some(canonical_stored) = canonicalize_with_missing_tail(&absolute)? else {
                return Ok(None);
            };
            let Ok(relative) = canonical_stored.strip_prefix(canonical_root) else {
                return Ok(None);
            };
            relative.to_path_buf()
        }
    };
    let Some(relative) = path_string(&relative) else {
        return Ok(None);
    };
    if relative.is_empty() {
        return Ok(None);
    }
    Ok(Some((relative, absolute)))
}

fn canonicalize_with_missing_tail(path: &Path) -> Result<Option<PathBuf>, String> {
    let mut cursor = path;
    let mut tail = Vec::new();
    loop {
        match std::fs::metadata(cursor) {
            Ok(_) => break,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let Some(name) = cursor.file_name() else {
                    return Ok(None);
                };
                tail.push(name.to_os_string());
                let Some(parent) = cursor.parent() else {
                    return Ok(None);
                };
                cursor = parent;
            }
            Err(error) => return Err(format!("stat indexed path {}: {error}", cursor.display())),
        }
    }
    let mut canonical = std::fs::canonicalize(cursor)
        .map_err(|error| format!("canonicalize indexed path {}: {error}", cursor.display()))?;
    for component in tail.iter().rev() {
        canonical.push(component);
    }
    Ok(Some(canonical))
}

fn path_string(path: &Path) -> Option<String> {
    Some(
        path.to_string_lossy()
            .replace(std::path::MAIN_SEPARATOR, "/"),
    )
}

fn lexical_normalize(path: &Path) -> PathBuf {
    use std::path::Component;
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            Component::Normal(value) => normalized.push(value),
            Component::RootDir | Component::Prefix(_) => normalized.push(component.as_os_str()),
        }
    }
    normalized
}

fn clean_specifier(specifier: &str) -> Option<String> {
    let trimmed = specifier;
    if trimmed.len() < 2 {
        return Some(trimmed.to_string());
    }
    let bytes = trimmed.as_bytes();
    let quoted = (bytes[0] == b'\'' && bytes[trimmed.len() - 1] == b'\'')
        || (bytes[0] == b'"' && bytes[trimmed.len() - 1] == b'"');
    Some(if quoted {
        trimmed[1..trimmed.len() - 1].to_string()
    } else {
        trimmed.to_string()
    })
}

fn is_relative_spec(specifier: &str) -> bool {
    clean_specifier(specifier)
        .is_some_and(|specifier| specifier.starts_with("./") || specifier.starts_with("../"))
}

fn has_loader_or_query(specifier: &str) -> bool {
    specifier.contains('?')
        || specifier.contains('#')
        || specifier.contains('!')
        || specifier.contains('%')
        || specifier.contains('\\')
}

fn resolve_relative_path(source: &str, specifier: &str) -> Option<String> {
    let source_parent = Path::new(source).parent().unwrap_or_else(|| Path::new(""));
    let mut parts = Vec::new();
    for component in source_parent
        .components()
        .chain(Path::new(specifier).components())
    {
        use std::path::Component;
        match component {
            Component::CurDir => {}
            Component::Normal(value) => parts.push(value.to_string_lossy().into_owned()),
            Component::ParentDir => {
                parts.pop()?;
            }
            Component::RootDir | Component::Prefix(_) => return None,
        }
    }
    (!parts.is_empty()).then(|| parts.join("/"))
}

fn candidate_paths(
    base: &str,
    source_lang: Option<ast_grep_language::SupportLang>,
    raw_spec: &str,
) -> Vec<String> {
    let mut candidates = match Path::new(raw_spec)
        .extension()
        .and_then(|value| value.to_str())
    {
        Some(extension) => explicit_candidates(base, source_lang, extension),
        None => extensionless_candidates(base, source_lang),
    };
    candidates.sort();
    candidates.dedup();
    candidates
}

fn explicit_candidates(
    base: &str,
    source_lang: Option<ast_grep_language::SupportLang>,
    extension: &str,
) -> Vec<String> {
    extension_aliases(extension)
        .into_iter()
        .map(|target_extension| replace_extension(base, target_extension))
        .filter(|candidate| compatible_path(source_lang, candidate))
        .collect()
}

fn extensionless_candidates(
    base: &str,
    source_lang: Option<ast_grep_language::SupportLang>,
) -> Vec<String> {
    if !is_javascript_family(source_lang) {
        return Vec::new();
    }
    let files = crate::parse::EXTENSION_LANGUAGES
        .iter()
        .map(|(extension, _)| format!("{base}.{extension}"));
    let indexes = [
        "index.js",
        "index.jsx",
        "index.mjs",
        "index.cjs",
        "index.ts",
        "index.tsx",
        "__init__.py",
        "init.lua",
    ]
    .into_iter()
    .map(|index| format!("{base}/{index}"));
    files
        .chain(indexes)
        .filter(|candidate| compatible_path(source_lang, candidate))
        .collect()
}

fn is_javascript_family(lang: Option<ast_grep_language::SupportLang>) -> bool {
    matches!(
        lang,
        Some(ast_grep_language::SupportLang::JavaScript)
            | Some(ast_grep_language::SupportLang::TypeScript)
            | Some(ast_grep_language::SupportLang::Tsx)
    )
}

fn extension_aliases(extension: &str) -> Vec<&str> {
    match extension.to_ascii_lowercase().as_str() {
        "js" => vec![extension, "ts", "tsx"],
        "jsx" => vec![extension, "tsx"],
        "mjs" => vec![extension, "mts"],
        "cjs" => vec![extension, "cts"],
        _ => vec![extension],
    }
}

fn replace_extension(path: &str, extension: &str) -> String {
    let path = Path::new(path);
    let stem = path.with_extension(extension);
    path_string(&stem).unwrap_or_else(|| path.to_string_lossy().into_owned())
}

fn compatible_path(source_lang: Option<ast_grep_language::SupportLang>, candidate: &str) -> bool {
    match (
        source_lang,
        crate::parse::language_for_path(Path::new(candidate)),
    ) {
        (Some(left), Some(right)) => left == right || js_ts_family(left, right),
        _ => false,
    }
}

fn js_ts_family(
    left: ast_grep_language::SupportLang,
    right: ast_grep_language::SupportLang,
) -> bool {
    matches!(
        (left, right),
        (
            ast_grep_language::SupportLang::JavaScript
                | ast_grep_language::SupportLang::TypeScript
                | ast_grep_language::SupportLang::Tsx,
            ast_grep_language::SupportLang::JavaScript
                | ast_grep_language::SupportLang::TypeScript
                | ast_grep_language::SupportLang::Tsx
        )
    )
}

fn dedup_physical(physical: Vec<(String, PathBuf)>) -> Vec<(String, PathBuf)> {
    let mut seen = HashSet::new();
    physical
        .into_iter()
        .filter(|(path, _)| seen.insert(path.clone()))
        .collect()
}

fn is_missing_candidate(
    specifier: &str,
    source_lang: Option<ast_grep_language::SupportLang>,
) -> bool {
    if !supports_source_relative(source_lang) {
        return false;
    }
    let extension = Path::new(specifier)
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase);
    let Some(extension) = extension else {
        return false;
    };
    // Header includes often name toolchain or system files. Keep this gate
    // conservative even though `.h` is indexable for source extraction.
    if matches!(
        source_lang,
        Some(ast_grep_language::SupportLang::C) | Some(ast_grep_language::SupportLang::Cpp)
    ) && matches!(extension.as_str(), "h" | "hpp" | "hh" | "hxx" | "h++")
    {
        return false;
    }
    crate::parse::language_for_extension(&extension).is_some()
}
