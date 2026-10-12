//! Harness-agnostic links between listed parent and worker sessions.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionSource {
    Active,
    Archived,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParentSession<'a> {
    pub session_id: &'a str,
    pub tool_call_results: &'a [String],
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CandidateSession<'a> {
    pub session_id: &'a str,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerLink {
    pub parent_id: String,
    pub evidence: String,
}

/// Link candidates mentioned in exactly one parent's tool-call result.
///
/// An ambiguous candidate remains unlinked, with the matching parent IDs
/// returned separately so callers can explain the ambiguity.
pub fn link_workers(
    parents: &[ParentSession<'_>],
    candidates: &[CandidateSession<'_>],
) -> Vec<Result<Option<WorkerLink>, Vec<String>>> {
    candidates
        .iter()
        .map(|candidate| {
            let matches: Vec<_> = parents
                .iter()
                .filter_map(|parent| {
                    parent
                        .tool_call_results
                        .iter()
                        .find(|result| result.contains(candidate.session_id))
                        .map(|evidence| (parent.session_id, evidence))
                })
                .collect();
            match matches.as_slice() {
                [] => Ok(None),
                [(parent_id, evidence)] => Ok(Some(WorkerLink {
                    parent_id: (*parent_id).to_owned(),
                    evidence: (*evidence).clone(),
                })),
                _ => {
                    let mut parent_ids: Vec<_> = matches
                        .iter()
                        .map(|(parent_id, _)| (*parent_id).to_owned())
                        .collect();
                    parent_ids.sort();
                    parent_ids.dedup();
                    Err(parent_ids)
                }
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn links_candidate_to_unique_parent_with_evidence() {
        let results = vec!["started worker session child-1".to_owned()];
        let parents = [ParentSession {
            session_id: "parent-1",
            tool_call_results: &results,
        }];
        let candidates = [CandidateSession {
            session_id: "child-1",
        }];

        assert_eq!(
            link_workers(&parents, &candidates),
            [Ok(Some(WorkerLink {
                parent_id: "parent-1".into(),
                evidence: results[0].clone(),
            }))]
        );
    }

    #[test]
    fn leaves_unmentioned_candidate_unlinked() {
        let results = vec!["started worker session child-1".to_owned()];
        let parents = [ParentSession {
            session_id: "parent-1",
            tool_call_results: &results,
        }];
        let candidates = [CandidateSession {
            session_id: "child-2",
        }];

        assert_eq!(link_workers(&parents, &candidates), [Ok(None)]);
    }

    #[test]
    fn reports_ambiguous_parent_ids_and_leaves_candidate_unlinked() {
        let first_result = vec!["started child-1".to_owned()];
        let second_result = vec!["created child-1".to_owned()];
        let parents = [
            ParentSession {
                session_id: "parent-b",
                tool_call_results: &first_result,
            },
            ParentSession {
                session_id: "parent-a",
                tool_call_results: &second_result,
            },
        ];
        let candidates = [CandidateSession {
            session_id: "child-1",
        }];

        assert_eq!(
            link_workers(&parents, &candidates),
            [Err(vec!["parent-a".into(), "parent-b".into()])]
        );
    }

    #[test]
    fn repeated_mentions_from_one_parent_are_not_ambiguous() {
        let results = vec!["child-1 started".to_owned(), "child-1 ready".to_owned()];
        let parents = [ParentSession {
            session_id: "parent-1",
            tool_call_results: &results,
        }];
        let candidates = [CandidateSession {
            session_id: "child-1",
        }];

        assert_eq!(
            link_workers(&parents, &candidates),
            [Ok(Some(WorkerLink {
                parent_id: "parent-1".into(),
                evidence: results[0].clone(),
            }))]
        );
    }
}
