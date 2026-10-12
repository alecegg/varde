//! Directive-line scanner for cognitive-complexity preprocessor regions.

use crate::model::{Entity, EntityKind, Span};

#[derive(Debug, Clone)]
struct Directive {
    line: usize,
    start: usize,
    end: usize,
    name: String,
    argument: String,
}

#[derive(Debug)]
struct OpenRegion {
    directive: Directive,
    branch: Option<Directive>,
    skip: bool,
}

/// Scan supported source text and emit conditional/alternative region markers.
/// Haskell callers must set `haskell_cpp` only when `LANGUAGE CPP` is present.
pub fn scan(source: &str, file_id: u32, enabled: bool, haskell_cpp: bool) -> Vec<Entity> {
    if !enabled || (haskell_cpp && !source.contains("{-# LANGUAGE CPP #-}")) {
        return Vec::new();
    }
    let directives = directives(source);
    let guard = include_guard(&directives);
    let mut stack = Vec::<OpenRegion>::new();
    let mut output = Vec::new();

    for directive in directives {
        match directive.name.as_str() {
            "if" | "ifdef" | "ifndef" => {
                let skip = guard == Some(directive.line);
                stack.push(OpenRegion {
                    directive,
                    branch: None,
                    skip,
                });
            }
            "elif" | "elseif" | "else" => {
                if let Some(open) = stack.last_mut() {
                    if let Some(branch) = open.branch.take() {
                        if !open.skip {
                            output.push(entity(
                                "preproc_branch",
                                file_id,
                                span(source, branch.start, directive.start),
                            ));
                        }
                    }
                    if !open.skip {
                        open.branch = Some(directive);
                    }
                }
            }
            "endif" => {
                if let Some(open) = stack.pop() {
                    if !open.skip {
                        if let Some(branch) = open.branch {
                            output.push(entity(
                                "preproc_branch",
                                file_id,
                                span(source, branch.start, directive.start),
                            ));
                        }
                        output.push(entity(
                            "preproc_if",
                            file_id,
                            span(source, open.directive.start, directive.end),
                        ));
                    }
                }
            }
            _ => {}
        }
    }
    output.sort_by_key(|entity| (entity.span.start_byte, entity.span.end_byte));
    output
}

/// Let a file-level directive that wraps a top-level callable participate in
/// that callable's containment-based complexity calculation. The copied
/// marker is clipped to the callable span; nested callables remain represented
/// by the scorer's normal callable-depth calculation.
pub fn attribute_top_level_regions(markers: &mut Vec<Entity>, entities: &[Entity]) {
    let originals = markers.clone();
    for marker in originals
        .iter()
        .filter(|entity| matches!(entity.name.as_str(), "preproc_if" | "preproc_branch"))
    {
        let top_level_callables: Vec<_> = entities
            .iter()
            .filter(|candidate| candidate.kind == EntityKind::Function)
            .filter(|candidate| contains(marker.span, candidate.span))
            .filter(|candidate| {
                !entities.iter().any(|parent| {
                    parent.kind == EntityKind::Function
                        && parent.span != candidate.span
                        && contains(parent.span, candidate.span)
                        && contains(marker.span, parent.span)
                })
            })
            .collect();
        for callable in top_level_callables {
            let mut attributed = marker.clone();
            attributed.span = callable.span;
            attributed.enclosing_function = Some(callable.name.clone());
            attributed.owner_type = callable.owner_type.clone();
            markers.push(attributed);
        }
    }
}

fn contains(outer: Span, inner: Span) -> bool {
    outer.start_byte <= inner.start_byte && outer.end_byte >= inner.end_byte
}

fn directives(source: &str) -> Vec<Directive> {
    let mut output = Vec::new();
    let mut offset = 0;
    for (line, raw) in source.split_inclusive('\n').enumerate() {
        let trimmed = raw.trim_start();
        if let Some(after_hash) = trimmed.strip_prefix('#') {
            let rest = after_hash.trim_start();
            let name_end = rest
                .find(|character: char| !character.is_ascii_alphanumeric() && character != '_')
                .unwrap_or(rest.len());
            let name = &rest[..name_end];
            if matches!(
                name,
                "if" | "ifdef" | "ifndef" | "elif" | "elseif" | "else" | "endif" | "define"
            ) {
                let argument = rest[name_end..].trim().to_string();
                let start = offset + raw.len() - trimmed.len();
                output.push(Directive {
                    line,
                    start,
                    end: offset + raw.trim_end_matches(['\r', '\n']).len(),
                    name: name.to_string(),
                    argument,
                });
            }
        }
        offset += raw.len();
    }
    output
}

/// Return the line of a conventional outer include guard, if present.
fn include_guard(directives: &[Directive]) -> Option<usize> {
    let first = directives.first()?;
    let guard_macro = guard_macro(first)?;
    let define = directives.get(1)?;
    let matching_name = define.name == "define" && first_word(&define.argument) == guard_macro;
    let adjacent = define.line == first.line + 1;
    let final_endif = directives.last().is_some_and(|last| last.name == "endif");
    (matching_name && adjacent && final_endif).then_some(first.line)
}

fn guard_macro(directive: &Directive) -> Option<String> {
    let compact: String = directive
        .argument
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    let candidate = match directive.name.as_str() {
        "ifndef" => compact.as_str(),
        "if" => {
            let negated = compact.strip_prefix('!')?;
            if let Some(name) = negated.strip_prefix("defined(") {
                name.strip_suffix(')')?
            } else {
                negated
            }
        }
        _ => return None,
    };
    valid_macro_identifier(candidate).then(|| candidate.to_owned())
}

fn valid_macro_identifier(value: &str) -> bool {
    let mut characters = value.chars();
    characters
        .next()
        .is_some_and(|first| first == '_' || first.is_ascii_alphabetic())
        && characters.all(|character| character == '_' || character.is_ascii_alphanumeric())
}

fn first_word(value: &str) -> &str {
    value
        .split(|character: char| !character.is_ascii_alphanumeric() && character != '_')
        .find(|part| !part.is_empty())
        .unwrap_or("")
}

fn span(source: &str, start: usize, end: usize) -> Span {
    let start = start.min(source.len());
    let end = end.min(source.len()).max(start);
    let start_before = &source[..start];
    let end_before = &source[..end];
    let start_line = start_before.bytes().filter(|byte| *byte == b'\n').count();
    let end_line = end_before.bytes().filter(|byte| *byte == b'\n').count();
    let start_col = start - start_before.rfind('\n').map_or(0, |index| index + 1);
    let end_col = end - end_before.rfind('\n').map_or(0, |index| index + 1);
    Span {
        start_byte: crate::model::saturating_u32(start),
        end_byte: crate::model::saturating_u32(end),
        start_line: crate::model::saturating_u32(start_line + 1),
        start_col: crate::model::saturating_u32(start_col),
        end_line: crate::model::saturating_u32(end_line + 1),
        end_col: crate::model::saturating_u32(end_col),
    }
}

fn entity(name: &str, file_id: u32, span: Span) -> Entity {
    Entity {
        kind: EntityKind::ControlFlow,
        name: name.to_string(),
        file_id,
        span,
        enclosing_function: None,
        method: None,
        path: None,
        status: None,
        body_shape: None,
        body_minhash: None,
        is_async: None,
        is_test: false,
        owner_type: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(source: &str, haskell_cpp: bool) -> Vec<(String, u32, u32)> {
        scan(source, 2, true, haskell_cpp)
            .into_iter()
            .map(|entity| (entity.name, entity.span.start_line, entity.span.end_line))
            .collect()
    }

    #[test]
    fn include_guard_is_ignored_and_inner_conditions_remain() {
        let source = "#ifndef HEADER_H\n#define HEADER_H\n#if FEATURE\nint x;\n#endif\n#endif\n";
        let found = names(source, false);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].0, "preproc_if");
        assert_eq!((found[0].1, found[0].2), (3, 5));
    }

    #[test]
    fn negated_if_include_guard_is_ignored_and_inner_conditions_remain() {
        let source = "#if !HEADER_H\n#define HEADER_H\n#if FEATURE\nint x;\n#endif\n#endif\n";
        let found = names(source, false);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].0, "preproc_if");
        assert_eq!((found[0].1, found[0].2), (3, 5));
    }

    #[test]
    fn negated_defined_include_guard_is_ignored() {
        let source = "#if !defined(HEADER_H)\n#define HEADER_H\nint x;\n#endif\n";
        assert!(names(source, false).is_empty());
    }

    #[test]
    fn negated_if_without_immediate_matching_define_remains_conditional() {
        let source = "#if !HEADER_H\nint x;\n#endif\n";
        let found = names(source, false);
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].0, "preproc_if");
        assert_eq!((found[0].1, found[0].2), (1, 3));
    }

    #[test]
    fn extern_c_conditionals_are_kept_as_distinct_regions() {
        let source =
            "#ifdef __cplusplus\nextern \"C\" {\n#endif\nint f();\n#ifdef __cplusplus\n}\n#endif\n";
        let found = names(source, false);
        assert_eq!(
            found
                .iter()
                .filter(|(name, _, _)| name == "preproc_if")
                .count(),
            2
        );
    }

    #[test]
    fn alternatives_and_nested_regions_emit_hybrid_markers() {
        let source = "#if A\n#if B\nx\n#endif\n#elif C\ny\n#else\nz\n#endif\n";
        let found = names(source, false);
        assert_eq!(
            found
                .iter()
                .filter(|(name, _, _)| name == "preproc_if")
                .count(),
            2
        );
        assert_eq!(
            found
                .iter()
                .filter(|(name, _, _)| name == "preproc_branch")
                .count(),
            2
        );
    }

    #[test]
    fn swift_elseif_and_haskell_cpp_gate_are_supported() {
        let swift = "#if os(macOS)\na\n#elseif canImport(X)\nb\n#else\nc\n#endif\n";
        assert_eq!(
            names(swift, false)
                .iter()
                .filter(|(n, _, _)| n == "preproc_branch")
                .count(),
            2
        );
        assert!(scan("#if A\n#endif\n", 0, true, true).is_empty());
        assert_eq!(
            scan("{-# LANGUAGE CPP #-}\n#if A\n#endif\n", 0, true, true).len(),
            1
        );
    }

    #[test]
    fn file_level_region_rolls_into_callable_and_nests_lambda_flow() {
        let source = "#if DEBUG\nvoid f() { auto callback = [] { if (ready) {} }; }\n#endif\n";
        let parsed = crate::parse::parse_source(&ast_grep_language::SupportLang::Cpp, source);
        let result = crate::extract::extract(&parsed, 0);
        let metrics = crate::complexity::function_complexities(&result.entities);
        let function = metrics.iter().find(|metric| metric.name == "f").unwrap();
        assert_eq!(function.cognitive, 4, "entities: {:?}", result.entities);
        assert!(result.entities.iter().any(|entity| {
            entity.name == "preproc_if" && entity.enclosing_function.as_deref() == Some("f")
        }));
    }
}
