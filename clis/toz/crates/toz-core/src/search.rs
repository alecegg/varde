//! Search: porter FTS + trigram FTS → RRF → proximity rerank → recency tiebreak → snippet.
//!
//! Scope filters (handle, source, content type, superseded) are pushed into SQL. Typo retry
//! kicks in only when both matchers return nothing.

use crate::store::{now, Store};
use anyhow::Result;
use rusqlite::{params_from_iter, types::Value as SqlValue};
use serde::Serialize;
use std::collections::HashMap;

const CANDIDATES: usize = 50;
const RRF_K: f64 = 60.0;
const PROXIMITY_WINDOW: usize = 200;
const PROXIMITY_BOOST: f64 = 1.5;
const SNIPPET_RADIUS: usize = 300;
const SNIPPET_LINES: usize = 6;
const RECENCY_FLOOR: f64 = 0.7;

#[derive(Debug, Clone, Default)]
pub struct SearchOpts {
    pub limit: usize,
    pub handle: Option<String>,
    /// Partial, case-insensitive match on label or source.
    pub source: Option<String>,
    pub content_type: Option<String>,
    pub include_superseded: bool,
    pub recency_floor: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Hit {
    pub handle: String,
    pub label: String,
    pub chunk: usize,
    pub stream: String,
    pub title: String,
    pub line_start: i64,
    pub line_end: i64,
    pub content_type: String,
    pub score: f64,
    pub age_secs: i64,
    pub snippet: String,
    /// `index` captures only: the backing file has changed since it was indexed.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub stale: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub project: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct QueryResult {
    pub query: String,
    /// Set when the original query found nothing and a corrected one was used.
    pub corrected: Option<String>,
    pub hits: Vec<Hit>,
}

struct Candidate {
    rowid: i64,
    rrf: f64,
}

struct ChunkMeta {
    handle: String,
    label: String,
    ordinal: i64,
    stream: String,
    title: String,
    line_start: i64,
    line_end: i64,
    content_type: String,
    created_at: i64,
    body: String,
    stale: bool,
}

pub fn search(store: &Store, queries: &[String], opts: &SearchOpts) -> Result<Vec<QueryResult>> {
    queries.iter().map(|q| search_one(store, q, opts)).collect()
}

fn search_one(store: &Store, query: &str, opts: &SearchOpts) -> Result<QueryResult> {
    let terms = terms_of(query);
    if terms.is_empty() {
        return Ok(QueryResult {
            query: query.into(),
            corrected: None,
            hits: Vec::new(),
        });
    }
    let (candidates, corrected) = search_candidates(store, &terms, opts)?;
    let active_terms: Vec<String> = match &corrected {
        Some(c) => terms_of(c),
        None => terms.clone(),
    };

    let mut hits = Vec::new();
    let t_now = now();
    let floor = opts.recency_floor.unwrap_or(RECENCY_FLOOR);
    for c in candidates {
        let Some(meta) = chunk_meta(store, c.rowid)? else {
            continue;
        };
        hits.push(hit_from_candidate(meta, c.rrf, &active_terms, t_now, floor));
    }
    hits.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    hits.truncate(opts.limit.max(1));
    Ok(QueryResult {
        query: query.into(),
        corrected,
        hits,
    })
}

fn search_candidates(
    store: &Store,
    terms: &[String],
    opts: &SearchOpts,
) -> Result<(Vec<Candidate>, Option<String>)> {
    let mut candidates = candidates_for(store, terms, opts)?;
    if candidates.is_empty() {
        if let Some(fixed) = correct_terms(store, terms)? {
            candidates = candidates_for(store, &fixed, opts)?;
            if !candidates.is_empty() {
                return Ok((candidates, Some(fixed.join(" "))));
            }
        }
    }
    Ok((candidates, None))
}

fn hit_from_candidate(meta: ChunkMeta, rrf: f64, terms: &[String], t_now: i64, floor: f64) -> Hit {
    let positions = term_positions(&meta.body.to_lowercase(), terms);
    let mut score = rrf;
    if terms.len() > 1 && all_within(&positions, PROXIMITY_WINDOW) {
        score *= PROXIMITY_BOOST;
    }
    let age = (t_now - meta.created_at).max(0);
    let age_hours = age as f64 / 3600.0;
    score *= (1.0 / (1.0 + age_hours / 24.0)).clamp(floor, 1.0);
    let snippet = snippet(&meta.body, &positions);
    Hit {
        handle: meta.handle,
        label: meta.label,
        chunk: meta.ordinal as usize,
        stream: meta.stream,
        title: meta.title,
        line_start: meta.line_start,
        line_end: meta.line_end,
        content_type: meta.content_type,
        score,
        age_secs: age,
        snippet,
        stale: meta.stale,
        project: None,
    }
}

/// Tokenise the user query: whitespace split, strip FTS-significant punctuation, lowercase.
pub fn terms_of(query: &str) -> Vec<String> {
    query
        .split_whitespace()
        .map(|t| {
            t.trim_matches(|c: char| !c.is_alphanumeric() && c != '_' && c != '-' && c != '.')
                .to_lowercase()
        })
        .filter(|t| !t.is_empty())
        .collect()
}

fn fts_query(terms: &[String], min_len: usize, and: bool) -> Option<String> {
    let quoted: Vec<String> = terms
        .iter()
        .filter(|t| t.chars().count() >= min_len)
        .map(|t| format!("\"{}\"", t.replace('"', "\"\"")))
        .collect();
    if quoted.is_empty() {
        return None;
    }
    Some(quoted.join(if and { " " } else { " OR " }))
}

fn candidates_for(store: &Store, terms: &[String], opts: &SearchOpts) -> Result<Vec<Candidate>> {
    // AND first for precision; if nothing, OR for recall.
    for and in [true, false] {
        let porter = ranked_terms(store, "chunks_porter", terms, 1, and, opts)?;
        let trigram = ranked_terms(store, "chunks_trigram", terms, 3, and, opts)?;
        if porter.is_empty() && trigram.is_empty() {
            if terms.len() == 1 {
                break;
            }
            continue;
        }
        return Ok(fuse_candidates(&porter, &trigram));
    }
    Ok(Vec::new())
}

fn ranked_terms(
    store: &Store,
    table: &str,
    terms: &[String],
    min_len: usize,
    and: bool,
    opts: &SearchOpts,
) -> Result<Vec<i64>> {
    match fts_query(terms, min_len, and) {
        Some(query) => ranked(store, table, &query, opts),
        None => Ok(Vec::new()),
    }
}

fn fuse_candidates(porter: &[i64], trigram: &[i64]) -> Vec<Candidate> {
    let mut fused: HashMap<i64, f64> = HashMap::new();
    for list in [porter, trigram] {
        for (rank, rowid) in list.iter().enumerate() {
            *fused.entry(*rowid).or_default() += 1.0 / (RRF_K + rank as f64 + 1.0);
        }
    }
    let mut out: Vec<Candidate> = fused
        .into_iter()
        .map(|(rowid, rrf)| Candidate { rowid, rrf })
        .collect();
    out.sort_by(|a, b| {
        b.rrf
            .partial_cmp(&a.rrf)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    out
}

/// Rowids from one FTS table, best first, with scope filters applied in SQL.
fn ranked(store: &Store, table: &str, fts: &str, opts: &SearchOpts) -> Result<Vec<i64>> {
    let mut sql = format!(
        "SELECT f.rowid FROM {table} f
         JOIN chunks ch ON ch.id = f.rowid
         JOIN captures c ON c.id = ch.capture_id
         WHERE {table} MATCH ?1"
    );
    let mut args: Vec<SqlValue> = vec![SqlValue::Text(fts.to_string())];
    if let Some(h) = &opts.handle {
        args.push(SqlValue::Text(h.clone()));
        sql.push_str(&format!(" AND c.handle = ?{}", args.len()));
    }
    if let Some(s) = &opts.source {
        args.push(SqlValue::Text(format!("%{}%", s.to_lowercase())));
        let n = args.len();
        sql.push_str(&format!(
            " AND (lower(c.label) LIKE ?{n} OR lower(c.source) LIKE ?{n})"
        ));
    }
    if let Some(t) = &opts.content_type {
        args.push(SqlValue::Text(t.clone()));
        sql.push_str(&format!(" AND ch.content_type = ?{}", args.len()));
    }
    if !opts.include_superseded && opts.handle.is_none() {
        sql.push_str(" AND c.superseded_by IS NULL");
    }
    sql.push_str(&format!(" ORDER BY bm25({table}) LIMIT {CANDIDATES}"));
    let mut stmt = store.conn().prepare(&sql)?;
    let rows = stmt.query_map(params_from_iter(args.iter()), |r| r.get::<_, i64>(0))?;
    Ok(rows.collect::<std::result::Result<Vec<_>, _>>()?)
}

fn chunk_meta(store: &Store, rowid: i64) -> Result<Option<ChunkMeta>> {
    use rusqlite::OptionalExtension;
    store
        .conn()
        .query_row(
            "SELECT c.handle, c.label, ch.ordinal, ch.stream, ch.title, ch.line_start, ch.line_end,
                    ch.content_type, c.created_at, ch.body, c.kind, c.source, c.file_mtime, c.file_hash
             FROM chunks ch JOIN captures c ON c.id = ch.capture_id WHERE ch.id = ?1",
            [rowid],
            |r| {
                let kind: String = r.get(10)?;
                let source: String = r.get(11)?;
                let mtime: Option<i64> = r.get(12)?;
                let hash: Option<Vec<u8>> = r.get(13)?;
                let stale = kind == "index" && crate::index::is_stale(&source, mtime, hash.as_deref());
                Ok(ChunkMeta {
                    handle: r.get(0)?,
                    label: r.get(1)?,
                    ordinal: r.get(2)?,
                    stream: r.get(3)?,
                    title: r.get(4)?,
                    line_start: r.get(5)?,
                    line_end: r.get(6)?,
                    content_type: r.get(7)?,
                    created_at: r.get(8)?,
                    body: r.get(9)?,
                    stale,
                })
            },
        )
        .optional()
        .map_err(Into::into)
}

/// Byte offsets of every occurrence of every term (on a lowercased body).
fn term_positions(lower: &str, terms: &[String]) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    for (ti, t) in terms.iter().enumerate() {
        let mut start = 0;
        while let Some(i) = lower[start..].find(t.as_str()) {
            out.push((start + i, ti));
            start += i + t.len().max(1);
        }
    }
    out.sort_unstable();
    out
}

/// True if some window of `width` bytes contains every distinct term index.
fn all_within(positions: &[(usize, usize)], width: usize) -> bool {
    let n_terms = positions
        .iter()
        .map(|p| p.1)
        .max()
        .map(|m| m + 1)
        .unwrap_or(0);
    if n_terms == 0 {
        return false;
    }
    let mut seen = vec![0usize; n_terms];
    let mut distinct = 0;
    let mut lo = 0;
    for hi in 0..positions.len() {
        let t = positions[hi].1;
        if seen[t] == 0 {
            distinct += 1;
        }
        seen[t] += 1;
        while positions[hi].0 - positions[lo].0 > width {
            let tl = positions[lo].1;
            seen[tl] -= 1;
            if seen[tl] == 0 {
                distinct -= 1;
            }
            lo += 1;
        }
        if distinct == n_terms {
            return true;
        }
    }
    false
}

/// Line-based snippet: the densest cluster of matching lines, capped at SNIPPET_LINES lines and
/// ~2×SNIPPET_RADIUS bytes. Whole body if it is already that small.
fn snippet(body: &str, positions: &[(usize, usize)]) -> String {
    let max_bytes = SNIPPET_RADIUS * 2;
    let lines: Vec<&str> = body.lines().collect();
    if lines.len() <= SNIPPET_LINES && body.len() <= max_bytes {
        return body.to_string();
    }
    // map byte offsets → line indices
    let starts = line_starts(&lines);
    let line_of = |pos: usize| match starts.binary_search(&pos) {
        Ok(i) => i,
        Err(i) => i.saturating_sub(1),
    };
    let mut hit_lines: Vec<usize> = positions.iter().map(|p| line_of(p.0)).collect();
    hit_lines.dedup();
    let start = if hit_lines.is_empty() {
        0
    } else {
        densest_hit_line(&hit_lines).saturating_sub(1)
    };
    let end = (start + SNIPPET_LINES).min(lines.len());
    render_snippet(&lines, start, end, max_bytes)
}

fn line_starts(lines: &[&str]) -> Vec<usize> {
    let mut starts = Vec::with_capacity(lines.len());
    let mut off = 0;
    for line in lines {
        starts.push(off);
        off += line.len() + 1;
    }
    starts
}

fn densest_hit_line(hit_lines: &[usize]) -> usize {
    let mut best = (0usize, hit_lines[0]);
    let mut lo = 0;
    for hi in 0..hit_lines.len() {
        while hit_lines[hi] - hit_lines[lo] >= SNIPPET_LINES {
            lo += 1;
        }
        if hi - lo + 1 > best.0 {
            best = (hi - lo + 1, hit_lines[lo]);
        }
    }
    best.1
}

fn render_snippet(lines: &[&str], start: usize, end: usize, max_bytes: usize) -> String {
    let mut out = String::new();
    if start > 0 {
        out.push_str("…\n");
    }
    let mut used = 0;
    for l in &lines[start..end] {
        let l = clip(l, max_bytes / 2);
        if used + l.len() > max_bytes {
            break;
        }
        used += l.len() + 1;
        out.push_str(&l);
        out.push('\n');
    }
    if end < lines.len() {
        out.push('…');
    }
    out.trim_end_matches('\n').to_string()
}

fn clip(s: &str, max: usize) -> String {
    if s.len() <= max {
        return s.to_string();
    }
    let mut i = max;
    while i > 0 && !s.is_char_boundary(i) {
        i -= 1;
    }
    format!("{}…", &s[..i])
}

/// Typo correction via the trigram index: OR the term's trigrams, take the best-matching chunks,
/// and pick the closest real word in their bodies. Returns corrected terms if any changed.
fn correct_terms(store: &Store, terms: &[String]) -> Result<Option<Vec<String>>> {
    let mut changed = false;
    let mut out = Vec::with_capacity(terms.len());
    for t in terms {
        match correct_term(store, t)? {
            Some(w) => {
                changed = true;
                out.push(w);
            }
            _ => out.push(t.clone()),
        }
    }
    Ok(if changed { Some(out) } else { None })
}

fn correct_term(store: &Store, term: &str) -> Result<Option<String>> {
    let n = term.chars().count();
    if n < 4 {
        return Ok(None);
    }
    let chars: Vec<char> = term.chars().collect();
    let grams: Vec<String> = chars.windows(3).map(|w| w.iter().collect()).collect();
    let Some(fts) = fts_query(&grams, 3, false) else {
        return Ok(None);
    };
    let mut stmt = store.conn().prepare(
        "SELECT body FROM chunks_trigram WHERE chunks_trigram MATCH ?1 ORDER BY bm25(chunks_trigram) LIMIT 10",
    )?;
    let bodies: Vec<String> = stmt
        .query_map([&fts], |r| r.get(0))?
        .collect::<std::result::Result<_, _>>()?;
    Ok(best_correction(term, n, &bodies))
}

fn best_correction(term: &str, n: usize, bodies: &[String]) -> Option<String> {
    let max_d = if n >= 8 { 2 } else { 1 };
    let mut best: Option<(usize, String)> = None;
    for body in bodies {
        for word in body.split(|c: char| !c.is_alphanumeric() && c != '_') {
            let wl = word.chars().count();
            if wl + 2 < n || wl > n + 2 {
                continue;
            }
            let w = word.to_lowercase();
            let d = strsim::levenshtein(term, &w);
            if d <= max_d && best.as_ref().is_none_or(|(bd, _)| d < *bd) {
                best = Some((d, w));
            }
        }
    }
    match best {
        Some((d, word)) if d > 0 => Some(word),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chunk::chunk_default;
    use crate::store::NewCapture;

    fn store_with(docs: &[(&str, &str)]) -> Store {
        let dir = std::env::temp_dir().join(format!("toz-search-{}", crate::rand::next_u64()));
        let mut s = Store::open(&dir.join("toz.db")).unwrap();
        for (label, body) in docs {
            let chunks: Vec<_> = chunk_default(body)
                .into_iter()
                .map(|c| ("stdout".to_string(), c))
                .collect();
            s.insert_capture(
                &NewCapture {
                    label,
                    kind: "run",
                    source: label,
                    source_key: label,
                    bytes: body.len(),
                    exit_code: Some(0),
                    session: None,
                    redactions: 0,
                    binary: false,
                    file_mtime: None,
                    file_hash: None,
                },
                &chunks,
            )
            .unwrap();
        }
        s
    }

    fn opts() -> SearchOpts {
        SearchOpts {
            limit: 5,
            ..Default::default()
        }
    }

    #[test]
    fn stemming_finds_variants() {
        let s = store_with(&[("a", "the caches were cached by the caching layer\n")]);
        let r = search(&s, &["cache".into()], &opts()).unwrap();
        assert_eq!(r[0].hits.len(), 1);
    }

    #[test]
    fn trigram_finds_substrings() {
        let s = store_with(&[("a", "fn useEffectHandler() {}\n")]);
        let r = search(&s, &["useEff".into()], &opts()).unwrap();
        assert_eq!(r[0].hits.len(), 1);
    }

    #[test]
    fn proximity_boosts_close_terms() {
        let far = format!("alpha {} beta\n", "x ".repeat(400));
        let s = store_with(&[("far", &far), ("near", "alpha beta together\n")]);
        let r = search(&s, &["alpha beta".into()], &opts()).unwrap();
        assert_eq!(r[0].hits[0].label, "near");
        assert_eq!(r[0].hits.len(), 2);
    }

    #[test]
    fn handle_and_source_filters() {
        let s = store_with(&[
            ("cargo test", "failure in parser\n"),
            ("git log", "failure noted\n"),
        ]);
        let by_source = search(
            &s,
            &["failure".into()],
            &SearchOpts {
                source: Some("cargo".into()),
                ..opts()
            },
        )
        .unwrap();
        assert_eq!(by_source[0].hits.len(), 1);
        assert_eq!(by_source[0].hits[0].label, "cargo test");
        let h = by_source[0].hits[0].handle.clone();
        let by_handle = search(
            &s,
            &["failure".into()],
            &SearchOpts {
                handle: Some(h),
                ..opts()
            },
        )
        .unwrap();
        assert_eq!(by_handle[0].hits.len(), 1);
    }

    #[test]
    fn superseded_hidden_unless_all() {
        let s = store_with(&[
            ("cargo test", "failure one\n"),
            ("cargo test", "failure two\n"),
        ]);
        let r = search(&s, &["failure".into()], &opts()).unwrap();
        assert_eq!(r[0].hits.len(), 1);
        assert!(r[0].hits[0].snippet.contains("two"));
        let all = search(
            &s,
            &["failure".into()],
            &SearchOpts {
                include_superseded: true,
                ..opts()
            },
        )
        .unwrap();
        assert_eq!(all[0].hits.len(), 2);
    }

    #[test]
    fn typo_is_corrected() {
        let s = store_with(&[("a", "the connection timeout was exceeded\n")]);
        let r = search(&s, &["conection".into()], &opts()).unwrap();
        assert_eq!(r[0].hits.len(), 1);
        assert!(r[0].corrected.is_some());
    }

    #[test]
    fn or_fallback_when_and_misses() {
        let s = store_with(&[("a", "only alpha here\n")]);
        let r = search(&s, &["alpha omega".into()], &opts()).unwrap();
        assert_eq!(r[0].hits.len(), 1);
    }

    #[test]
    fn snippet_windows_around_hits() {
        let body: String = (1..=60)
            .map(|i| {
                if i == 30 {
                    "needle in the middle\n".to_string()
                } else {
                    format!("filler {i}\n")
                }
            })
            .collect();
        let s = store_with(&[("a", &body)]);
        let r = search(&s, &["needle".into()], &opts()).unwrap();
        let snip = &r[0].hits[0].snippet;
        assert!(snip.contains("needle"));
        assert!(snip.lines().count() <= 8, "{snip}");
        assert!(snip.starts_with('…') && snip.ends_with('…'));
        assert!(snip.contains("filler 29") && snip.contains("filler 31"));
    }

    #[test]
    fn fts_special_chars_are_safe() {
        let s = store_with(&[("a", "error: expected `;` near (foo) AND bar\n")]);
        let r = search(
            &s,
            &["(foo) AND".into(), "\"quoted\"".into(), "-".into()],
            &opts(),
        )
        .unwrap();
        assert_eq!(r.len(), 3);
        assert_eq!(r[0].hits.len(), 1);
    }

    #[test]
    fn typo_correction_escapes_embedded_quotes() {
        let s = store_with(&[("a", "unrelated payload\n")]);
        let r = search(&s, &["abc\"def".into()], &opts()).unwrap();
        assert!(r[0].hits.is_empty());
    }
}
