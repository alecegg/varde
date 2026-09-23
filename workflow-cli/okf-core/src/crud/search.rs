//! `concept search --text`: ranked lexical full-text search across Concept
//! bodies and frontmatter values.
//!
//! This is a *lexical* search only — substring matching against normalized
//! text, no fuzzy/edit-distance matching and no embeddings. It composes
//! additively with exact-value `--field` filtering. Combined searches match
//! fields and score text during one traversal.
//!
//! Ported (lexical portion only) from `pi-llm-wiki`'s `searchWiki`/
//! `normalizeText`/`queryTerms`/`scoreField`/`chunkPage` design — semantic
//! re-ranking, embeddings, score fusion, and pseudo-relevance-feedback query
//! expansion are all out of scope here.
//!
//! Traversal mirrors [`crate::registry::search`]'s bundle-tree walk: hidden
//! entries, artifact directories (`target`, `node_modules`), and symlinks
//! are skipped; `index.md`/`log.md`/`README.md` are bundle bookkeeping,
//! never Concepts. Slugs are derived with the shared
//! [`crate::crud::relative_slug`] helper so `search --text` reports the
//! same slug identity as `list`/`search --field`.

use crate::bundle::is_reserved;
use crate::frontmatter::FrontmatterError;
use serde::Serialize;
use std::collections::BTreeMap;
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

/// Typed errors for `search --text`. Distinct from
/// [`crate::registry::RegistryError`] even though the variants mirror it
/// exactly (both wrap the same [`crate::walk::WalkError`] shape) — full-text
/// search is not a registry query, and reusing `RegistryError` here would
/// hand callers registry-flavored variants for an unrelated feature (see
/// ARCHITECTURE-004).
#[derive(Debug, Error)]
pub enum TextSearchError {
    #[error("failed to read bundle directory `{path}`: {source}")]
    ReadDirFailed { path: PathBuf, source: io::Error },
    #[error("failed to read `{path}`: {source}")]
    ReadFailed { path: PathBuf, source: io::Error },
    #[error("`{path}` is not a valid OKF concept: {source}")]
    InvalidConcept {
        path: PathBuf,
        source: FrontmatterError,
    },
}

impl From<crate::walk::WalkError> for TextSearchError {
    fn from(err: crate::walk::WalkError) -> Self {
        match err {
            crate::walk::WalkError::ReadDirFailed { path, source } => {
                TextSearchError::ReadDirFailed { path, source }
            }
            crate::walk::WalkError::ReadFailed { path, source } => {
                TextSearchError::ReadFailed { path, source }
            }
            crate::walk::WalkError::InvalidConcept { path, source } => {
                TextSearchError::InvalidConcept { path, source }
            }
        }
    }
}

/// One `--text` search hit: the Concept's slug, its required `type`, its
/// total relevance score, and a short preview of the best-matching passage.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct TextSearchResult {
    pub slug: String,
    #[serde(rename = "type")]
    pub type_: Option<String>,
    pub score: i64,
    pub preview: String,
}

/// Weight of a term match in the Concept's slug (the `--field`-analogous
/// strong identifier).
const SLUG_WEIGHT: i64 = 3;
/// Weight of a term match in the `title` frontmatter field.
const TITLE_WEIGHT: i64 = 5;
/// Weight of a term match in the `aliases` frontmatter field.
const ALIASES_WEIGHT: i64 = 6;
/// Weight of a term match in the `tags` frontmatter field.
const TAGS_WEIGHT: i64 = 4;
/// Weight of a term match in any other frontmatter string/array value.
const OTHER_FIELD_WEIGHT: i64 = 2;
/// Weight of a term match in a body chunk's heading line.
const HEADING_WEIGHT: i64 = 4;
/// Weight of a term match in a body chunk's content.
const CHUNK_BODY_WEIGHT: i64 = 1;

/// Preview length (chars) taken from the best-scoring chunk.
const CHUNK_PREVIEW_LEN: usize = 180;
/// Preview length (chars) taken from the start of the body when no chunk
/// scores above zero.
const FALLBACK_PREVIEW_LEN: usize = 200;

/// Default result cap for `--limit` when the caller doesn't override it.
pub const DEFAULT_LIMIT: usize = 20;

/// Ranked lexical full-text search across Concept bodies and frontmatter
/// values in one or more bundles.
///
/// Every Concept's frontmatter and body is scored against `query`'s
/// normalized terms (see [module docs](self) for the weighting); only
/// Concepts with a total score `> 0` are returned, sorted by score
/// descending and tie-broken alphabetically by slug, then truncated to
/// `limit`. Same-slug collisions across bundles keep **later bundles
/// winning**, mirroring [`crate::registry::search`]. An empty/whitespace-only
/// (or otherwise term-less) `query` returns an empty result, not every
/// Concept.
pub fn search_text(
    bundles: &[PathBuf],
    query: &str,
    limit: usize,
) -> Result<Vec<TextSearchResult>, TextSearchError> {
    search_text_matching(bundles, query, &[], limit)
}

/// Search Concept text while applying exact frontmatter filters.
///
/// Field matching and text scoring share one traversal. Results preserve
/// later-bundle precedence and apply `limit` after merging and ranking.
pub fn search_text_matching(
    bundles: &[PathBuf],
    query: &str,
    filters: &[(String, String)],
    limit: usize,
) -> Result<Vec<TextSearchResult>, TextSearchError> {
    let terms = query_terms(query);
    if terms.is_empty() {
        return Ok(Vec::new());
    }

    let mut merged: BTreeMap<String, TextSearchResult> = BTreeMap::new();
    for bundle in bundles {
        crate::walk::visit_concepts(bundle, &is_reserved, |file| {
            if let Some(result) = score_file(bundle, file, filters, &terms) {
                merged.insert(result.slug.clone(), result);
            }
        })?;
    }

    let mut results: Vec<TextSearchResult> = merged.into_values().collect();
    results.sort_by(|a, b| b.score.cmp(&a.score).then_with(|| a.slug.cmp(&b.slug)));
    results.truncate(limit);
    Ok(results)
}

fn score_file(
    bundle: &Path,
    file: crate::walk::WalkedFile,
    filters: &[(String, String)],
    terms: &[String],
) -> Option<TextSearchResult> {
    if !crate::registry::matches_all(&file.frontmatter, filters) {
        return None;
    }
    let type_ = file
        .frontmatter
        .get("type")
        .and_then(|value| value.as_str())
        .filter(|value| !value.is_empty())
        .map(str::to_string);
    let slug = crate::crud::relative_slug(bundle, &file.path);
    let mut score = score_text(&slug, terms, SLUG_WEIGHT);
    score += score_frontmatter(&file.frontmatter, terms);
    let (body_score, preview) = score_body(&file.body, terms);
    score += body_score;
    (score > 0).then_some(TextSearchResult {
        slug,
        type_,
        score,
        preview,
    })
}

fn score_frontmatter(frontmatter: &serde_yaml::Value, terms: &[String]) -> i64 {
    let Some(map) = frontmatter.as_mapping() else {
        return 0;
    };
    map.iter()
        .filter_map(|(key, value)| Some((key.as_str()?, value)))
        .map(|(key, value)| score_value(value, terms, field_weight(key)))
        .sum()
}

fn field_weight(field: &str) -> i64 {
    match field {
        "title" => TITLE_WEIGHT,
        "aliases" => ALIASES_WEIGHT,
        "tags" => TAGS_WEIGHT,
        _ => OTHER_FIELD_WEIGHT,
    }
}

/// Normalize text for lexical matching: lowercase, strip/replace
/// separators (`-`, `_`, `.`, `/`, `\`) and punctuation with spaces,
/// collapse whitespace. No CJK-specific handling (out of scope per the
/// design reference).
fn normalize_text(value: &str) -> String {
    let lowered = value.to_lowercase();
    let mut normalized = String::with_capacity(lowered.len());
    for c in lowered.chars() {
        if c.is_alphanumeric() {
            normalized.push(c);
        } else {
            normalized.push(' ');
        }
    }
    normalized.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Normalize and tokenize a query into deduplicated terms of at least 2
/// characters, in first-seen order.
fn query_terms(query: &str) -> Vec<String> {
    let normalized = normalize_text(query);
    let mut seen = std::collections::HashSet::new();
    let mut terms = Vec::new();
    for part in normalized.split_whitespace() {
        if part.chars().count() >= 2 && seen.insert(part.to_string()) {
            terms.push(part.to_string());
        }
    }
    terms
}

/// Substring-match `terms` against normalized `text`, `weight` points per
/// distinct matching term.
fn score_text(text: &str, terms: &[String], weight: i64) -> i64 {
    let normalized = normalize_text(text);
    if normalized.is_empty() {
        return 0;
    }
    terms
        .iter()
        .filter(|term| normalized.contains(term.as_str()))
        .count() as i64
        * weight
}

/// Flatten a YAML value (string/number/bool/sequence/mapping) to
/// space-joined text, then [`score_text`] it. Sequences/mappings recurse so
/// e.g. `tags: [a, b]` scores each element.
fn score_value(value: &serde_yaml::Value, terms: &[String], weight: i64) -> i64 {
    let mut flattened = String::new();
    flatten_value(value, &mut flattened);
    score_text(&flattened, terms, weight)
}

fn flatten_value(value: &serde_yaml::Value, out: &mut String) {
    match value {
        serde_yaml::Value::String(s) => {
            out.push_str(s);
            out.push(' ');
        }
        serde_yaml::Value::Number(n) => {
            out.push_str(&n.to_string());
            out.push(' ');
        }
        serde_yaml::Value::Bool(b) => {
            out.push_str(&b.to_string());
            out.push(' ');
        }
        serde_yaml::Value::Sequence(items) => {
            for item in items {
                flatten_value(item, out);
            }
        }
        serde_yaml::Value::Mapping(map) => {
            for (_, v) in map {
                flatten_value(v, out);
            }
        }
        serde_yaml::Value::Tagged(tagged) => flatten_value(&tagged.value, out),
        serde_yaml::Value::Null => {}
    }
}

/// One heading-delimited section of a Concept body: the heading text (empty
/// for the intro section before the first heading) and its content.
struct Chunk {
    heading: String,
    content: String,
}

/// Split a markdown body into heading-delimited chunks. Content before the
/// first heading (if any) becomes the intro chunk (`heading == ""`).
fn chunk_body(body: &str) -> Vec<Chunk> {
    let mut chunks = Vec::new();
    let mut heading = String::new();
    let mut content_lines: Vec<&str> = Vec::new();

    for line in body.lines() {
        if let Some(h) = heading_text(line) {
            if !content_lines.is_empty() || !heading.is_empty() {
                chunks.push(Chunk {
                    heading: heading.clone(),
                    content: content_lines.join("\n"),
                });
            }
            heading = h;
            content_lines = Vec::new();
        } else {
            content_lines.push(line);
        }
    }
    if !content_lines.is_empty() || !heading.is_empty() {
        chunks.push(Chunk {
            heading,
            content: content_lines.join("\n"),
        });
    }
    chunks
}

/// Whether `line` is a markdown ATX heading (`^#{1,6}\s+.+`); returns the
/// heading text (trimmed) when it is.
fn heading_text(line: &str) -> Option<String> {
    let trimmed = line.trim_start();
    let hashes = trimmed.chars().take_while(|&c| c == '#').count();
    if hashes == 0 || hashes > 6 {
        return None;
    }
    let rest = &trimmed[hashes..];
    if !rest.starts_with(|c: char| c.is_whitespace()) {
        return None;
    }
    let text = rest.trim();
    if text.is_empty() {
        return None;
    }
    Some(text.to_string())
}

/// Score a Concept body by heading-chunked sections, tracking the
/// best-scoring chunk. Returns `(best_chunk_score, preview)`; when no chunk
/// scores above zero, the preview falls back to the first ~200 chars of the
/// body (empty body -> empty preview, zero score).
fn score_body(body: &str, terms: &[String]) -> (i64, String) {
    if body.trim().is_empty() {
        return (0, String::new());
    }

    let mut best_score = 0i64;
    let mut best_preview = String::new();
    for chunk in chunk_body(body) {
        let mut score = score_text(&chunk.heading, terms, HEADING_WEIGHT);
        score += score_text(&chunk.content, terms, CHUNK_BODY_WEIGHT);
        if score > best_score {
            best_score = score;
            best_preview = chunk_preview(&chunk.heading, &chunk.content);
        }
    }

    if best_score > 0 {
        (best_score, best_preview)
    } else {
        (0, fallback_preview(body))
    }
}

/// Render a chunk's preview: up to [`CHUNK_PREVIEW_LEN`] chars of its
/// content, newlines collapsed to spaces, prefixed with `#<heading> — `
/// when the chunk has a heading.
fn chunk_preview(heading: &str, content: &str) -> String {
    let text: String = content
        .trim()
        .chars()
        .take(CHUNK_PREVIEW_LEN)
        .collect::<String>()
        .replace('\n', " ");
    if heading.is_empty() {
        text
    } else {
        format!("#{heading} — {text}")
    }
}

/// The first [`FALLBACK_PREVIEW_LEN`] chars of the raw body, newlines
/// collapsed to spaces, used when no chunk scored above zero.
fn fallback_preview(body: &str) -> String {
    body.trim()
        .chars()
        .take(FALLBACK_PREVIEW_LEN)
        .collect::<String>()
        .replace('\n', " ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::tempdir;
    use std::path::Path;

    fn write(dir: &Path, name: &str, content: &str) {
        std::fs::write(dir.join(name), content).unwrap();
    }

    #[test]
    fn normalize_text_strips_punctuation_and_separators() {
        assert_eq!(
            normalize_text("Use-Rust_v1.0/beta\\x"),
            "use rust v1 0 beta x"
        );
        assert_eq!(normalize_text("  Multiple   Spaces  "), "multiple spaces");
        assert_eq!(normalize_text("Hello, World!"), "hello world");
    }

    #[test]
    fn query_terms_dedupes_and_drops_short_tokens() {
        assert_eq!(
            query_terms("Rust rust a RUST-lang"),
            vec!["rust".to_string(), "lang".to_string()]
        );
        assert_eq!(query_terms("a I x"), Vec::<String>::new());
    }

    #[test]
    fn empty_query_returns_no_results() {
        let dir = tempdir("okf-core-search-empty-query");
        write(
            &dir,
            "doc.md",
            "---\ntype: decision\ntitle: Rust\n---\n# Rust\nBody\n",
        );
        assert_eq!(search_text(&[dir], "", 20).unwrap(), Vec::new());
    }

    #[test]
    fn no_match_returns_empty() {
        let dir = tempdir("okf-core-search-no-match");
        write(
            &dir,
            "doc.md",
            "---\ntype: decision\ntitle: Rust\n---\n# Rust\nBody about the language\n",
        );
        assert_eq!(
            search_text(&[dir], "zzz-nonexistent", 20).unwrap(),
            Vec::new()
        );
    }

    #[test]
    fn title_match_outranks_body_only_match_for_same_term() {
        let dir = tempdir("okf-core-search-weighting");
        write(
            &dir,
            "titled.md",
            "---\ntype: decision\ntitle: Postgres tuning\n---\n# Notes\nUnrelated content.\n",
        );
        write(
            &dir,
            "body-only.md",
            "---\ntype: decision\ntitle: Something else\n---\n# Notes\nPostgres appears only here.\n",
        );
        let got = search_text(&[dir], "postgres", 20).unwrap();
        assert_eq!(
            got.iter().map(|r| r.slug.as_str()).collect::<Vec<_>>(),
            vec!["titled", "body-only"],
            "a title match must outrank a body-only match: {got:?}"
        );
        assert!(got[0].score > got[1].score);
    }

    #[test]
    fn heading_chunk_preview_extraction() {
        let dir = tempdir("okf-core-search-chunk-preview");
        write(
            &dir,
            "doc.md",
            "---\ntype: decision\ntitle: Doc\n---\nIntro text, unrelated.\n\n## Configuration\nSet the widget flag to enable turbo mode.\n\n## Other\nNot relevant here.\n",
        );
        let got = search_text(&[dir], "turbo", 20).unwrap();
        assert_eq!(got.len(), 1);
        assert!(
            got[0].preview.starts_with("#Configuration"),
            "preview must come from the best-scoring chunk: {:?}",
            got[0].preview
        );
        assert!(got[0].preview.contains("turbo mode"));
    }

    #[test]
    fn fallback_preview_used_when_no_chunk_scores() {
        let dir = tempdir("okf-core-search-fallback-preview");
        write(
            &dir,
            "doc.md",
            "---\ntype: decision\ntitle: Widget alpha\n---\nJust an intro paragraph with no headings at all.\n",
        );
        let got = search_text(&[dir], "widget", 20).unwrap();
        assert_eq!(got.len(), 1);
        assert!(
            got[0].preview.starts_with("Just an intro paragraph"),
            "must fall back to the body start: {:?}",
            got[0].preview
        );
    }

    #[test]
    fn aliases_and_tags_are_searchable() {
        let dir = tempdir("okf-core-search-aliases-tags");
        write(
            &dir,
            "doc.md",
            "---\ntype: decision\ntitle: Doc\naliases:\n  - turbocharge\ntags:\n  - performance\n---\n# Body\nNothing relevant.\n",
        );
        let got = search_text(std::slice::from_ref(&dir), "turbocharge", 20).unwrap();
        assert_eq!(got.len(), 1);
        let got = search_text(&[dir], "performance", 20).unwrap();
        assert_eq!(got.len(), 1);
    }

    #[test]
    fn slug_match_contributes_to_score() {
        let dir = tempdir("okf-core-search-slug");
        write(
            &dir,
            "use-rust.md",
            "---\ntype: decision\ntitle: A decision\n---\n# Body\nNo mention here.\n",
        );
        let got = search_text(&[dir], "rust", 20).unwrap();
        assert_eq!(got.len(), 1);
        assert_eq!(got[0].slug, "use-rust");
    }

    #[test]
    fn limit_truncates_results() {
        let dir = tempdir("okf-core-search-limit");
        for i in 0..5 {
            write(
                &dir,
                &format!("doc-{i}.md"),
                "---\ntype: decision\ntitle: Rust notes\n---\n# Rust\nBody\n",
            );
        }
        let got = search_text(&[dir], "rust", 2).unwrap();
        assert_eq!(got.len(), 2);
    }

    #[test]
    fn results_sorted_by_score_then_slug() {
        let dir = tempdir("okf-core-search-sort");
        write(
            &dir,
            "b.md",
            "---\ntype: decision\ntitle: Rust\n---\n# Rust\nRust rust rust.\n",
        );
        write(
            &dir,
            "a.md",
            "---\ntype: decision\ntitle: Rust\n---\n# Rust\nRust rust rust.\n",
        );
        let got = search_text(&[dir], "rust", 20).unwrap();
        // Equal scores: tie-break alphabetically by slug.
        assert_eq!(
            got.iter().map(|r| r.slug.as_str()).collect::<Vec<_>>(),
            vec!["a", "b"]
        );
    }

    #[test]
    fn nested_slug_matches_relative_slug_format() {
        let dir = tempdir("okf-core-search-nested");
        std::fs::create_dir(dir.join("pattern")).unwrap();
        write(
            &dir,
            "pattern/rule-a.md",
            "---\ntype: pattern\ntitle: Rust rule\n---\n# Rust\nBody\n",
        );
        let got = search_text(&[dir], "rust", 20).unwrap();
        assert_eq!(got.len(), 1);
        assert_eq!(got[0].slug, "pattern/rule-a");
    }

    #[test]
    fn missing_type_is_absent_optional_not_an_error() {
        let dir = tempdir("okf-core-search-missing-type");
        write(&dir, "bad.md", "---\ntitle: no type\n---\nRust\n");
        let got = search_text(&[dir], "rust", 20).unwrap();
        assert_eq!(got.len(), 1);
        assert_eq!(got[0].type_, None);
    }

    #[test]
    fn hidden_and_reserved_files_are_excluded() {
        let dir = tempdir("okf-core-search-hidden");
        write(&dir, "index.md", "# rust index");
        write(
            &dir,
            "doc.md",
            "---\ntype: decision\ntitle: Rust\n---\n# Rust\nBody\n",
        );
        let sub = dir.join("target");
        std::fs::create_dir(&sub).unwrap();
        write(
            &sub,
            "bad.md",
            "---\ntype: decision\ntitle: Rust\n---\n# Rust\nBody\n",
        );
        let got = search_text(&[dir], "rust", 20).unwrap();
        assert_eq!(
            got.iter().map(|r| r.slug.as_str()).collect::<Vec<_>>(),
            vec!["doc"]
        );
    }

    #[test]
    fn field_filters_compose_with_text_search() {
        let dir = tempdir("okf-core-search-fields");
        write(
            &dir,
            "stable.md",
            "---\ntype: decision\nstatus: stable\n---\n# Rust\nStable choice.\n",
        );
        write(
            &dir,
            "draft.md",
            "---\ntype: decision\nstatus: draft\n---\n# Rust\nDraft choice.\n",
        );
        let filters = vec![("status".to_string(), "stable".to_string())];
        let got = search_text_matching(&[dir], "rust", &filters, 20).unwrap();
        assert_eq!(
            got.iter().map(|hit| hit.slug.as_str()).collect::<Vec<_>>(),
            vec!["stable"]
        );
    }

    #[test]
    fn combined_search_preserves_later_bundle_precedence() {
        let personal = tempdir("okf-core-search-fields-personal");
        let project = tempdir("okf-core-search-fields-project");
        write(
            &personal,
            "shared.md",
            "---\ntype: decision\nstatus: stable\n---\n# Rust\nPersonal copy.\n",
        );
        write(
            &project,
            "shared.md",
            "---\ntype: decision\nstatus: stable\n---\n# Rust\nProject copy.\n",
        );
        let filters = vec![("status".to_string(), "stable".to_string())];
        let got = search_text_matching(&[personal, project], "rust", &filters, 20).unwrap();
        assert_eq!(got.len(), 1);
        assert!(got[0].preview.contains("Project copy"));
    }
}
