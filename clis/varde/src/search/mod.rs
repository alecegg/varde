//! Search sources. Each adapter turns one module's query API into the
//! `varde-contracts` search contract; this crate is where the modules meet.
//! Adapters take already-resolved locations and never read the environment.

mod code;
mod friction;
mod knowledge;
mod toz;

pub use code::CodeSearch;
pub use friction::FrictionSearch;
pub use knowledge::KnowledgeSearch;
pub use toz::{TozScope, TozSearch};

use clap::{Arg, ArgAction, Command, value_parser};
use serde_json::{Value, json};
use std::ffi::OsString;
use std::path::PathBuf;
use std::process::ExitCode;
use toz_core::config::Config;
use toz_core::project::Project;
use varde_contracts::{SearchHit, SearchQuery, SearchSource, SourceResult};
use varde_core::envelope;
use varde_workflow_core::memory::MemoryPaths;

/// Source names in output order.
const SOURCES: [&str; 6] = ["code", "docs", "knowledge", "plans", "output", "friction"];

fn unavailable(source: &str, reason: impl Into<String>) -> SourceResult {
    SourceResult::Unavailable {
        source: source.to_string(),
        reason: reason.into(),
    }
}

fn command() -> Command {
    Command::new("search")
        .bin_name("varde search")
        .about("Search code, docs, knowledge, plans, captured output and friction")
        .arg(Arg::new("query").required(true).help("Text to search for"))
        .arg(
            Arg::new("in")
                .long("in")
                .value_delimiter(',')
                .value_parser(SOURCES)
                .help("Sources to search, comma separated [default: all]"),
        )
        .arg(
            Arg::new("limit")
                .long("limit")
                .value_parser(value_parser!(u32).range(1..))
                .default_value("5")
                .help("Most hits per source"),
        )
        .arg(
            Arg::new("json")
                .long("json")
                .action(ArgAction::SetTrue)
                .help("Print the machine-output envelope"),
        )
}

/// A source ready to search, or the result that says why it is not.
enum Slot {
    Ready(Box<dyn SearchSource>),
    Failed(SourceResult),
}

/// Where each store lives, resolved once from the environment.
struct Locations {
    repo_root: PathBuf,
    db_path: PathBuf,
    cfg: Result<Config, String>,
    paths: Result<MemoryPaths, String>,
}

impl Locations {
    fn resolve() -> Result<Self, String> {
        let project = Project::resolve(None).map_err(|error| format!("{error:#}"))?;
        let db_path = project.db_path().map_err(|error| format!("{error:#}"))?;
        Ok(Self {
            paths: MemoryPaths::resolve(&project.root).map_err(|error| error.to_string()),
            cfg: Config::load().map_err(|error| format!("{error:#}")),
            repo_root: project.root,
            db_path,
        })
    }

    fn toz_search(&self, scope: TozScope) -> Result<TozSearch, String> {
        match (&self.cfg, &self.paths) {
            (Ok(cfg), Ok(paths)) => Ok(TozSearch::new(
                scope,
                cfg.clone(),
                self.db_path.clone(),
                self.repo_root.clone(),
                paths.working.path.clone(),
            )),
            (Err(reason), _) | (_, Err(reason)) => Err(reason.clone()),
        }
    }

    fn slot(&self, name: &str) -> Slot {
        let failed = |reason: &str| Slot::Failed(unavailable(name, reason));
        let toz = |scope: TozScope| match self.toz_search(scope) {
            Ok(search) => Slot::Ready(Box::new(search)),
            Err(reason) => failed(&reason),
        };
        let paths = |build: fn(&MemoryPaths) -> Box<dyn SearchSource>| match &self.paths {
            Ok(paths) => Slot::Ready(build(paths)),
            Err(reason) => failed(reason),
        };
        match name {
            "code" => Slot::Ready(Box::new(CodeSearch::new(
                self.repo_root.clone(),
                varde_code::db::path::repo_db_path(&self.repo_root),
            ))),
            "docs" => toz(TozScope::Docs),
            "plans" => toz(TozScope::Plans),
            "output" => toz(TozScope::Output),
            "knowledge" => paths(|p| Box::new(KnowledgeSearch::new(p.knowledge.path.clone()))),
            _ => paths(|p| Box::new(FrictionSearch::new(p.learn.path.clone()))),
        }
    }
}

/// Search `selected` sources; results come back in `SOURCES` order. Sources
/// run concurrently, except docs and plans, which share one toz store and
/// run one after the other.
fn search_all(selected: &[&str], query: &SearchQuery) -> Vec<SourceResult> {
    let locations = Locations::resolve();
    if let Ok(locations) = &locations
        && selected.contains(&"plans")
        && let Ok(plans) = locations.toz_search(TozScope::Plans)
        && plans.plans_unindexed()
    {
        eprintln!(
            "varde search: indexing plan and review files (first run); this can take a while..."
        );
    }
    let slots: Vec<Slot> = selected
        .iter()
        .map(|name| match &locations {
            Ok(locations) => locations.slot(name),
            Err(reason) => Slot::Failed(unavailable(name, reason)),
        })
        .collect();
    let (shared, separate): (Vec<_>, Vec<_>) = slots
        .into_iter()
        .enumerate()
        .partition(|(index, _)| matches!(selected[*index], "docs" | "plans"));
    let mut lanes: Vec<Vec<(usize, Slot)>> = separate.into_iter().map(|slot| vec![slot]).collect();
    if !shared.is_empty() {
        lanes.push(shared);
    }
    let mut results: Vec<(usize, SourceResult)> = std::thread::scope(|scope| {
        let handles: Vec<_> = lanes
            .into_iter()
            .map(|lane| {
                let sources = lane
                    .iter()
                    .map(|(index, _)| (*index, selected[*index]))
                    .collect::<Vec<_>>();
                let handle = scope.spawn(move || run_lane(lane, query));
                (sources, handle)
            })
            .collect();
        handles
            .into_iter()
            .flat_map(|(sources, handle)| join_lane(handle.join(), &sources))
            .collect()
    });
    results.sort_by_key(|(index, _)| *index);
    results.into_iter().map(|(_, result)| result).collect()
}

fn run_lane(lane: Vec<(usize, Slot)>, query: &SearchQuery) -> Vec<(usize, SourceResult)> {
    lane.into_iter()
        .map(|(index, slot)| match slot {
            Slot::Ready(source) => (index, source.search(query)),
            Slot::Failed(result) => (index, result),
        })
        .collect()
}

fn join_lane(
    result: std::thread::Result<Vec<(usize, SourceResult)>>,
    sources: &[(usize, &str)],
) -> Vec<(usize, SourceResult)> {
    match result {
        Ok(results) => results,
        Err(_) => sources
            .iter()
            .map(|(index, source)| (*index, unavailable(source, "source panicked")))
            .collect(),
    }
}

fn hit_json(hit: &SearchHit) -> Value {
    json!({
        "source": hit.source,
        "title": hit.title,
        "location": hit.location,
        "snippet": hit.snippet,
        "score": hit.score,
    })
}

fn group_json(result: &SourceResult) -> Value {
    match result {
        SourceResult::Hits { source, hits } => json!({
            "source": source,
            "status": "ok",
            "hits": hits.iter().map(hit_json).collect::<Vec<_>>(),
        }),
        SourceResult::Unavailable { source, reason } => json!({
            "source": source,
            "status": "unavailable",
            "reason": reason,
            "hits": [],
        }),
    }
}

fn render_text(results: &[SourceResult]) -> String {
    let mut out = String::new();
    for result in results {
        match result {
            SourceResult::Hits { source, hits } => {
                out.push_str(&format!("## {source} ({})\n", hits.len()));
                for hit in hits {
                    out.push_str(&format!("- {}  {}\n", hit.title, hit.location));
                    let snippet = hit.snippet.trim();
                    if !snippet.is_empty() {
                        out.push_str(&format!("    {}\n", snippet.replace('\n', " ")));
                    }
                }
            }
            SourceResult::Unavailable { source, reason } => {
                out.push_str(&format!("## {source} (unavailable)\n- {reason}\n"));
            }
        }
    }
    out
}

/// `varde search <query>`: argv includes the program name.
pub fn run(args: Vec<OsString>) -> ExitCode {
    let matches = match command().try_get_matches_from(args) {
        Ok(matches) => matches,
        Err(error) => error.exit(),
    };
    let query = SearchQuery {
        text: matches
            .get_one::<String>("query")
            .cloned()
            .unwrap_or_default(),
        limit: matches.get_one::<u32>("limit").map_or(5, |n| *n as usize),
    };
    let requested: Vec<&String> = matches
        .get_many::<String>("in")
        .into_iter()
        .flatten()
        .collect();
    let selected: Vec<&str> = SOURCES
        .into_iter()
        .filter(|name| requested.is_empty() || requested.iter().any(|r| r.as_str() == *name))
        .collect();
    let results = search_all(&selected, &query);
    if matches.get_flag("json") {
        let groups: Vec<Value> = results.iter().map(group_json).collect();
        let meta = json!({"query": query.text, "limit": query.limit});
        println!("{}", envelope::success(json!({"groups": groups}), meta));
    } else {
        print!("{}", render_text(&results));
    }
    ExitCode::SUCCESS
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn panicking_lane_reports_each_source_as_unavailable() {
        let joined = std::thread::spawn(|| -> Vec<(usize, SourceResult)> {
            panic!("source lane failed");
        })
        .join();
        let results = join_lane(joined, &[(1, "docs"), (3, "plans")]);

        assert_eq!(results.len(), 2);
        for ((index, result), (expected_index, source)) in
            results.iter().zip([(1, "docs"), (3, "plans")])
        {
            assert_eq!(*index, expected_index);
            let group = group_json(result);
            assert_eq!(group["source"], source);
            assert_eq!(group["status"], "unavailable");
            assert_eq!(group["reason"], "source panicked");
        }
    }
}
