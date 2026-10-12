//! Same-file recursion binding shared by the language call matchers.
//!
//! Matchers report syntactic references; this module owns arity/owner binding
//! and cycle detection so language grammars do not implement scoring policy.

use crate::model::{Entity, EntityKind, Span};
use ast_grep_language::SupportLang;

/// Invoke the selected language matcher and resolve its same-file references.
pub(super) fn extract(
    lang: SupportLang,
    root: &crate::extract::langs::ParsedNode<'_>,
    file_id: u32,
) -> Vec<Entity> {
    let (callables, references) = crate::extract::langs::match_callees(lang, root);
    let owner_scoped = matches!(
        lang,
        SupportLang::CSharp
            | SupportLang::Java
            | SupportLang::Kotlin
            | SupportLang::Scala
            | SupportLang::Swift
            | SupportLang::Dart
            | SupportLang::Cpp
            | SupportLang::Ruby
            | SupportLang::Solidity
    );
    let mut entities = resolve(&callables, &references, owner_scoped);
    for entity in &mut entities {
        entity.file_id = file_id;
    }
    entities
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Qualifier {
    None,
    SelfLike,
    NamedType,
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Callable {
    /// Lookup owner (type owner for methods, lexical parent for nested free
    /// functions, and `None` for module-level functions).
    pub owner: Option<String>,
    /// Class/interface owner for the emitted function-metric metadata.
    pub owner_type: Option<String>,
    /// Whether a bare call can name this declaration in free-function
    /// languages. Nested named functions set this while using their lexical
    /// parent as `owner`; class methods leave it false.
    pub unqualified_callable: bool,
    pub name: String,
    pub required_args: u16,
    pub total_args: u16,
    pub file_id: u32,
    pub span: Span,
    /// Name token span, used for the emitted `recursive_call` marker.
    pub name_span: Span,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CalleeReference {
    pub caller: usize,
    pub name: String,
    pub argument_count: u16,
    pub qualifier: Qualifier,
    /// For `Type.f`, this is the type name. Self-like qualifiers leave it empty.
    pub qualifier_name: Option<String>,
}

/// Return one marker for every callable in a same-file recursive cycle.
///
/// The `owner_scoped_unqualified` flag describes the language's lookup rule:
/// class-scoped languages resolve bare calls against the current owner, while
/// free-function languages resolve them against the file-level owner.
pub fn resolve(
    callables: &[Callable],
    references: &[CalleeReference],
    owner_scoped_unqualified: bool,
) -> Vec<Entity> {
    let mut edges = vec![Vec::<usize>::new(); callables.len()];
    for reference in references {
        let Some(caller) = callables.get(reference.caller) else {
            continue;
        };
        for (target_id, target) in callables.iter().enumerate() {
            if target.file_id != caller.file_id || target.name != reference.name {
                continue;
            }
            if reference.argument_count < target.required_args
                || reference.argument_count > target.total_args
            {
                continue;
            }
            let owner_matches = match reference.qualifier {
                Qualifier::Other => false,
                Qualifier::SelfLike => target.owner == caller.owner,
                Qualifier::NamedType => {
                    reference.qualifier_name.as_deref() == target.owner.as_deref()
                        && target.owner == caller.owner
                }
                Qualifier::None if owner_scoped_unqualified => target.owner == caller.owner,
                Qualifier::None => target.unqualified_callable && target.owner == caller.owner,
            };
            if owner_matches && !edges[reference.caller].contains(&target_id) {
                edges[reference.caller].push(target_id);
            }
        }
    }

    strongly_connected_members(&edges)
        .into_iter()
        .enumerate()
        .filter_map(|(index, recursive)| recursive.then_some(index))
        .map(|index| {
            let callable = &callables[index];
            Entity {
                kind: EntityKind::ControlFlow,
                name: "recursive_call".to_string(),
                file_id: callable.file_id,
                span: callable.name_span,
                enclosing_function: Some(callable.name.clone()),
                method: None,
                path: None,
                status: None,
                body_shape: None,
                body_minhash: None,
                is_async: None,
                is_test: false,
                owner_type: callable.owner_type.clone(),
            }
        })
        .collect()
}

/// Kosaraju's two-pass SCC algorithm; singleton components are recursive only
/// when they contain a self-edge.
fn strongly_connected_members(edges: &[Vec<usize>]) -> Vec<bool> {
    let mut visited = vec![false; edges.len()];
    let mut order = Vec::with_capacity(edges.len());
    for start in 0..edges.len() {
        if visited[start] {
            continue;
        }
        let mut pending = vec![(start, false)];
        while let Some((node, expanded)) = pending.pop() {
            if expanded {
                order.push(node);
            } else if !visited[node] {
                visited[node] = true;
                pending.push((node, true));
                pending.extend(
                    edges[node]
                        .iter()
                        .rev()
                        .filter(|target| !visited[**target])
                        .map(|target| (*target, false)),
                );
            }
        }
    }

    let mut reverse = vec![Vec::new(); edges.len()];
    for (source, targets) in edges.iter().enumerate() {
        for target in targets {
            reverse[*target].push(source);
        }
    }
    visited.fill(false);
    let mut recursive = vec![false; edges.len()];
    for start in order.into_iter().rev() {
        if visited[start] {
            continue;
        }
        let mut component = Vec::new();
        let mut pending = vec![start];
        visited[start] = true;
        while let Some(node) = pending.pop() {
            component.push(node);
            for parent in &reverse[node] {
                if !visited[*parent] {
                    visited[*parent] = true;
                    pending.push(*parent);
                }
            }
        }
        if component.len() > 1 || edges[start].contains(&start) {
            for node in component {
                recursive[node] = true;
            }
        }
    }
    recursive
}

#[cfg(test)]
mod tests {
    use super::*;

    fn span(start: u32) -> Span {
        Span {
            start_byte: start,
            end_byte: start + 1,
            start_line: 1,
            start_col: start,
            end_line: 1,
            end_col: start + 1,
        }
    }

    fn callable(owner: Option<&str>, name: &str, start: u32) -> Callable {
        Callable {
            owner: owner.map(str::to_owned),
            owner_type: owner.map(str::to_owned),
            unqualified_callable: owner.is_none(),
            name: name.into(),
            required_args: 0,
            total_args: 0,
            file_id: 1,
            span: span(start),
            name_span: span(start),
        }
    }

    fn ref_to(caller: usize, name: &str, qualifier: Qualifier) -> CalleeReference {
        CalleeReference {
            caller,
            name: name.into(),
            argument_count: 0,
            qualifier,
            qualifier_name: None,
        }
    }

    #[test]
    fn direct_recursion_is_one_marker_even_with_multiple_self_calls() {
        let functions = [callable(None, "f", 3)];
        let refs = [
            ref_to(0, "f", Qualifier::None),
            ref_to(0, "f", Qualifier::None),
        ];
        let markers = resolve(&functions, &refs, false);
        assert_eq!(markers.len(), 1);
        assert_eq!(markers[0].span, span(3));
    }

    #[test]
    fn overload_delegation_and_other_receiver_do_not_create_recursion() {
        let mut small = callable(Some("Worker"), "run", 3);
        small.total_args = 1;
        let mut overload = callable(Some("Worker"), "run", 8);
        overload.required_args = 1;
        overload.total_args = 1;
        let mut other = ref_to(0, "run", Qualifier::Other);
        other.argument_count = 1;
        assert!(resolve(&[small, overload], &[other], true).is_empty());
    }

    #[test]
    fn every_member_of_a_cycle_is_marked_once() {
        let functions = [callable(None, "a", 1), callable(None, "b", 4)];
        let refs = [
            ref_to(0, "b", Qualifier::None),
            ref_to(1, "a", Qualifier::None),
        ];
        assert_eq!(resolve(&functions, &refs, false).len(), 2);
    }

    #[test]
    fn cross_file_edges_do_not_create_recursion() {
        let caller = callable(None, "a", 1);
        let mut callee = callable(None, "b", 4);
        callee.file_id = 2;
        let refs = [
            ref_to(0, "b", Qualifier::None),
            ref_to(1, "a", Qualifier::None),
        ];
        assert!(resolve(&[caller, callee], &refs, false).is_empty());
    }

    #[test]
    fn owner_and_arity_disambiguate_bindings() {
        let mut method = callable(Some("Worker"), "run", 1);
        method.required_args = 1;
        method.total_args = 2;
        let other_owner = callable(Some("Other"), "run", 4);
        let caller = callable(Some("Worker"), "caller", 7);
        let mut refs = ref_to(2, "run", Qualifier::NamedType);
        refs.qualifier_name = Some("Worker".into());
        refs.argument_count = 1;
        let back_edge = ref_to(0, "caller", Qualifier::None);
        assert_eq!(
            resolve(&[method, other_owner, caller], &[refs, back_edge], true).len(),
            2
        );
    }

    #[test]
    fn same_named_nested_function_self_call_marks_only_nested_callable() {
        let outer = callable(None, "visit", 1);
        let mut nested = callable(Some("visit"), "visit", 5);
        nested.unqualified_callable = true;
        nested.owner_type = None;
        let markers = resolve(
            &[outer, nested],
            &[ref_to(1, "visit", Qualifier::None)],
            false,
        );
        assert_eq!(markers.len(), 1);
        assert_eq!(markers[0].span, span(5));
    }
}
