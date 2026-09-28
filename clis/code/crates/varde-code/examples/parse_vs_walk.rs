//! Throwaway profiler: isolate tree-sitter parse cost from the extract walk.
//!
//! Usage: cargo run --release --example parse_vs_walk -- <repo_root>
//!
//! Reads every supported source file once, then times three things across the
//! whole repo (single-threaded, so the numbers are comparable per-phase):
//!   1. read+utf8 (I/O baseline)
//!   2. parse_source only (tree-sitter)
//!   3. extract::extract (parse + the merged entity/symbol walk)
//!
//! walk cost = (3) - (2). Prints totals and the parse:walk ratio.

use std::time::Instant;
use varde_code::extract;
use varde_code::parse::{language_for_path, parse_source};
use varde_code::scan::list_source_files;

fn main() {
    let root = std::env::args()
        .nth(1)
        .expect("usage: parse_vs_walk <repo_root>");
    let files = list_source_files(&root).expect("list files");
    let (sources, bytes_total) = load_sources(&files);
    eprintln!("supported files: {}  bytes: {}", sources.len(), bytes_total);
    warm_sources(&sources);
    let reps = 5;
    let parse_only = measure_parse(&sources, reps);
    let (parse_plus_walk, ent, sym) = measure_extract(&sources, reps);
    let walk = parse_plus_walk.saturating_sub(parse_only);
    eprintln!("parse_only        = {parse_only:?}");
    eprintln!("parse+walk        = {parse_plus_walk:?}");
    eprintln!("walk (difference) = {walk:?}");
    eprintln!(
        "ratio parse:walk  = {:.2} : {:.2}",
        parse_only.as_secs_f64() / parse_plus_walk.as_secs_f64(),
        walk.as_secs_f64() / parse_plus_walk.as_secs_f64(),
    );
    eprintln!("(last-file entities={ent} symbols={sym})");
}

type Source = (ast_grep_language::SupportLang, String);

fn load_sources(files: &[varde_code::scan::SourceFile]) -> (Vec<Source>, usize) {
    let mut sources = Vec::new();
    let mut bytes_total = 0;
    for file in files {
        let path = std::path::Path::new(&file.path);
        let Some(language) = language_for_path(path) else {
            continue;
        };
        let Ok(source) = std::fs::read_to_string(path) else {
            continue;
        };
        bytes_total += source.len();
        sources.push((language, source));
    }
    (sources, bytes_total)
}

fn warm_sources(sources: &[Source]) {
    for (language, source) in sources {
        let parsed = parse_source(language, source);
        std::hint::black_box(extract::extract(&parsed, 0));
    }
}

fn measure_parse(sources: &[Source], repetitions: u32) -> std::time::Duration {
    let started = Instant::now();
    for _ in 0..repetitions {
        for (language, source) in sources {
            std::hint::black_box(parse_source(language, source));
        }
    }
    started.elapsed() / repetitions
}

fn measure_extract(sources: &[Source], repetitions: u32) -> (std::time::Duration, usize, usize) {
    let started = Instant::now();
    let mut entity_count = 0;
    let mut symbol_count = 0;
    for _ in 0..repetitions {
        for (language, source) in sources {
            let parsed = parse_source(language, source);
            let extracted = extract::extract(&parsed, 0);
            entity_count = extracted.entities.len();
            symbol_count = extracted.symbols.len();
            std::hint::black_box((&extracted.entities, &extracted.symbols));
        }
    }
    (started.elapsed() / repetitions, entity_count, symbol_count)
}
