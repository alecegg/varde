//! Skill `requires`/`recommends` frontmatter relations.
//!
//! A skill declares the siblings it needs in its `SKILL.md` frontmatter as
//! flow lists of skill directory names: `requires: [varde-code]` is hard
//! (installed with the skill) and `recommends: [varde-toz]` is soft (a hint
//! only, never installed implicitly).

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

/// The skill every install includes implicitly; skills never list it.
pub const IMPLICIT_SKILL: &str = "varde-manage";

/// The relations one skill declares.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Relations {
    /// Skills installed with this one.
    pub requires: Vec<String>,
    /// Skills that work better alongside this one.
    pub recommends: Vec<String>,
}

/// A malformed relation value, an unknown skill name, or a `requires` cycle.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RelationError {
    /// The value of `requires` or `recommends` is not a flow list of names.
    Malformed { key: &'static str, value: String },
    /// A name has no skill.
    Unknown(String),
    /// A `requires` cycle, from the first repeated name back to it.
    Cycle(Vec<String>),
}

impl fmt::Display for RelationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Malformed { key, value } => {
                write!(
                    formatter,
                    "`{key}` is not a flow list of skill names: {value}"
                )
            }
            Self::Unknown(name) => write!(formatter, "unknown skill `{name}`"),
            Self::Cycle(path) => write!(formatter, "`requires` cycle: {}", path.join(" -> ")),
        }
    }
}

impl Error for RelationError {}

/// Read the `requires` and `recommends` keys from `SKILL.md` frontmatter text.
pub fn parse(frontmatter: &str) -> Result<Relations, RelationError> {
    let mut relations = Relations::default();
    for line in frontmatter.lines() {
        let Some((key, rest)) = relation_key(line) else {
            continue;
        };
        let names = parse_list(key, rest)?;
        match key {
            "requires" => relations.requires = names,
            _ => relations.recommends = names,
        }
    }
    Ok(relations)
}

/// Every name in `selected` plus its transitive `requires`, sorted and
/// deduplicated. `requires_of` returns `None` for an unknown skill.
pub fn closure(
    selected: &[String],
    requires_of: impl Fn(&str) -> Option<Vec<String>>,
) -> Result<Vec<String>, RelationError> {
    let mut seeds = selected.to_vec();
    seeds.sort();
    seeds.dedup();
    let mut visited = BTreeSet::new();
    for seed in &seeds {
        visit(seed, &requires_of, &mut Vec::new(), &mut visited)?;
    }
    Ok(visited.into_iter().collect())
}

/// A top-level `requires:` or `recommends:` line's key and value text. Indented
/// lines and other keys are ignored.
fn relation_key(line: &str) -> Option<(&'static str, &str)> {
    for key in ["requires", "recommends"] {
        if let Some(rest) = line
            .strip_prefix(key)
            .and_then(|rest| rest.strip_prefix(':'))
        {
            return Some((key, rest));
        }
    }
    None
}

/// A flow list (`[a, b]`), a bare name, or nothing. Items may be quoted, and
/// an empty list or trailing comma is allowed.
fn parse_list(key: &'static str, rest: &str) -> Result<Vec<String>, RelationError> {
    let value = rest.trim();
    if value.is_empty() {
        return Ok(Vec::new());
    }
    let malformed = || RelationError::Malformed {
        key,
        value: value.to_string(),
    };
    let mut names = Vec::new();
    match value.strip_prefix('[') {
        Some(inner) => {
            let inner = inner.strip_suffix(']').ok_or_else(malformed)?;
            for item in inner.split(',') {
                if item.trim().is_empty() {
                    continue;
                }
                names.push(parse_name(item).ok_or_else(malformed)?);
            }
        }
        None => names.push(parse_name(value).ok_or_else(malformed)?),
    }
    Ok(names)
}

/// One bare or quoted skill directory name.
fn parse_name(item: &str) -> Option<String> {
    let name = item.trim().trim_matches(['"', '\'']);
    let malformed = name.is_empty()
        || name
            .chars()
            .any(|c| c.is_whitespace() || "[]{},".contains(c));
    if malformed {
        None
    } else {
        Some(name.to_string())
    }
}

/// Follow one name's `requires` depth first, recording visited names and
/// reporting a name already on the current path as a cycle.
fn visit<F: Fn(&str) -> Option<Vec<String>>>(
    name: &str,
    requires_of: &F,
    path: &mut Vec<String>,
    visited: &mut BTreeSet<String>,
) -> Result<(), RelationError> {
    if let Some(at) = path.iter().position(|on_path| on_path == name) {
        let mut cycle = path[at..].to_vec();
        cycle.push(name.to_string());
        return Err(RelationError::Cycle(cycle));
    }
    if visited.contains(name) {
        return Ok(());
    }
    let mut requires = requires_of(name).ok_or_else(|| RelationError::Unknown(name.to_string()))?;
    requires.sort();
    requires.dedup();
    path.push(name.to_string());
    for required in &requires {
        visit(required, requires_of, path, visited)?;
    }
    path.pop();
    visited.insert(name.to_string());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn names(items: &[&str]) -> Vec<String> {
        items.iter().map(|item| item.to_string()).collect()
    }

    fn requires_of<'a>(
        edges: &'a BTreeMap<&'static str, &'static [&'static str]>,
    ) -> impl Fn(&str) -> Option<Vec<String>> + 'a {
        move |name| {
            edges
                .get(name)
                .map(|targets| targets.iter().map(|t| t.to_string()).collect())
        }
    }

    #[test]
    fn parse_reads_both_flow_lists() {
        let frontmatter = "name: varde-scan\nrequires: [varde-code]\nrecommends: [varde-toz]\n";
        assert_eq!(
            parse(frontmatter).unwrap(),
            Relations {
                requires: names(&["varde-code"]),
                recommends: names(&["varde-toz"]),
            }
        );
    }

    #[test]
    fn parse_defaults_missing_keys_to_empty() {
        assert_eq!(parse("name: varde-code\n").unwrap(), Relations::default());
    }

    #[test]
    fn parse_reads_empty_lists_and_bare_names() {
        let relations = parse("requires: []\nrecommends:\n").unwrap();
        assert_eq!(relations, Relations::default());
        let relations = parse("requires: varde-code\n").unwrap();
        assert_eq!(relations.requires, names(&["varde-code"]));
    }

    #[test]
    fn parse_ignores_indented_and_unrelated_keys() {
        let frontmatter = "metadata:\n  requires: [varde-code]\nother: requires\n";
        assert_eq!(parse(frontmatter).unwrap(), Relations::default());
    }

    #[test]
    fn parse_rejects_a_malformed_value() {
        let error = parse("requires: [varde-code, \n").unwrap_err();
        assert!(
            matches!(
                error,
                RelationError::Malformed {
                    key: "requires",
                    ..
                }
            ),
            "{error:?}"
        );
    }

    #[test]
    fn closure_adds_transitive_requires_sorted_and_deduplicated() {
        let edges: BTreeMap<&str, &[&str]> = BTreeMap::from([
            ("varde-a", &["varde-c", "varde-b"][..]),
            ("varde-b", &["varde-d"][..]),
            ("varde-c", &["varde-d"][..]),
            ("varde-d", &[][..]),
        ]);
        let selected = names(&["varde-c", "varde-a"]);
        assert_eq!(
            closure(&selected, requires_of(&edges)).unwrap(),
            names(&["varde-a", "varde-b", "varde-c", "varde-d"])
        );
    }

    #[test]
    fn closure_of_an_empty_selection_is_empty() {
        let edges: BTreeMap<&str, &[&str]> = BTreeMap::new();
        assert_eq!(
            closure(&[], requires_of(&edges)).unwrap(),
            Vec::<String>::new()
        );
    }

    #[test]
    fn closure_reports_unknown_names() {
        let edges: BTreeMap<&str, &[&str]> = BTreeMap::from([("varde-a", &["varde-missing"][..])]);
        let error = closure(&names(&["varde-a"]), requires_of(&edges)).unwrap_err();
        assert_eq!(error, RelationError::Unknown("varde-missing".to_string()));
        let error = closure(&names(&["varde-absent"]), requires_of(&edges)).unwrap_err();
        assert_eq!(error, RelationError::Unknown("varde-absent".to_string()));
    }

    #[test]
    fn closure_reports_a_cycle_distinct_from_an_unknown_name() {
        let edges: BTreeMap<&str, &[&str]> =
            BTreeMap::from([("varde-a", &["varde-b"][..]), ("varde-b", &["varde-a"][..])]);
        let error = closure(&names(&["varde-a"]), requires_of(&edges)).unwrap_err();
        let RelationError::Cycle(path) = error else {
            panic!("expected a cycle, got {error:?}");
        };
        assert!(path.contains(&"varde-a".to_string()));
        assert!(path.contains(&"varde-b".to_string()));
    }

    #[test]
    fn closure_reports_a_self_reference_as_a_cycle() {
        let edges: BTreeMap<&str, &[&str]> = BTreeMap::from([("varde-a", &["varde-a"][..])]);
        let error = closure(&names(&["varde-a"]), requires_of(&edges)).unwrap_err();
        assert!(matches!(error, RelationError::Cycle(_)), "{error:?}");
    }

    #[test]
    fn closure_does_not_add_the_implicit_skill() {
        let edges: BTreeMap<&str, &[&str]> = BTreeMap::from([("varde-a", &[][..])]);
        assert_eq!(
            closure(&names(&["varde-a"]), requires_of(&edges)).unwrap(),
            names(&["varde-a"])
        );
        assert_eq!(IMPLICIT_SKILL, "varde-manage");
    }
}
