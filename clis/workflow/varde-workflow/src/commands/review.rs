//! Reviewer evidence and subject commands.

use crate::cli::{ReviewArgs, ReviewCommand};
use crate::commands::error::{InternalError, report_error};
use crate::output::{print_failure, print_success};
use crate::review_gates;
use anyhow::Result;
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

pub fn run(args: ReviewArgs) -> Result<()> {
    match args.command {
        ReviewCommand::Init(args) => {
            let result = match (
                args.plan.as_deref(),
                args.subject.as_deref(),
                args.contract.as_deref(),
            ) {
                (Some(plan), None, None) => {
                    with_locked_repository(&args.repository, |repository| {
                        review_gates::initialize_plan(
                            repository,
                            plan,
                            &args.scope,
                            &args.exclude,
                            &args.artifact,
                            args.tier_evidence.as_deref(),
                        )
                    })
                }
                (None, Some(subject), Some(contract)) => {
                    with_locked_repository(&args.repository, |repository| {
                        review_gates::initialize_bounded(
                            repository,
                            subject,
                            contract,
                            &args.scope,
                            &args.exclude,
                            &args.artifact,
                            args.tier_evidence.as_deref(),
                        )
                    })
                }
                _ => {
                    return report_error(
                        &InternalError("use --plan, or use --subject with --contract".into()),
                        args.json,
                    );
                }
            };
            finish(result, args.json)
        }
        ReviewCommand::BindWorktree(args) => finish(
            with_worktree_repository(&current_repository()?, Some(&args.worktree), |repository| {
                crate::review_worktrees::bind(repository, &args)
            }),
            args.json,
        ),
        ReviewCommand::InspectWorktree(args) => finish(
            with_binding_repository(&args.subject, &args.binding, |repository| {
                crate::review_worktrees::inspect(repository, &args.subject, &args.binding)
            }),
            args.json,
        ),
        ReviewCommand::ReleaseWorktree(args) => finish(
            with_binding_repository(&args.subject, &args.binding, |repository| {
                crate::review_worktrees::release(repository, &args)
            }),
            args.json,
        ),
        ReviewCommand::AbandonWorktree(args) => finish(
            with_binding_repository(&args.subject, &args.binding, |repository| {
                crate::review_worktrees::abandon(repository, &args)
            }),
            args.json,
        ),
        ReviewCommand::Contract(args) => finish(
            with_repository(|repository| {
                review_gates::update_bounded_contract(
                    repository,
                    &args.subject,
                    &args.expected_version,
                    &args.file,
                )
            }),
            args.json,
        ),
        ReviewCommand::Expand(args) => finish(
            with_repository(|repository| {
                review_gates::expand_scope(
                    repository,
                    &args.subject,
                    &args.expected_version,
                    &args.scope,
                    &args.artifact,
                    args.tier_evidence.as_deref(),
                )
            }),
            args.json,
        ),
        ReviewCommand::Inspect(args) => finish(
            with_repository(|repository| {
                review_gates::inspect(repository, &args.subject, &args.phase)
            }),
            args.json,
        ),
        ReviewCommand::Record(args) => finish(
            with_repository(|repository| {
                review_gates::record(
                    repository,
                    &args.subject,
                    &args.expected_version,
                    &args.file,
                )
            }),
            args.json,
        ),
        ReviewCommand::Check(args) => {
            let checked = match (&args.repository, &args.worktree, &args.binding) {
                (Some(repository), Some(worktree), Some(binding)) => {
                    with_worktree_repository(repository, Some(worktree), |parent| {
                        let caller = current_repository()?;
                        if caller != worktree.canonicalize()? {
                            return Err(review_gates::invalid(
                                "worktree check must run in its registered checkout",
                            ));
                        }
                        crate::review_worktrees::check(
                            parent,
                            &args.subject,
                            binding,
                            worktree,
                            &args.checkpoint,
                        )
                    })
                }
                _ => with_repository(|repository| {
                    review_gates::check(repository, &args.subject, &args.checkpoint)
                }),
            };
            let result = match checked {
                Ok(result) => result,
                Err(error) => return report_review_error(&error, args.json),
            };
            if result.ready {
                finish(Ok(serde_json::to_value(result)?), args.json)
            } else {
                let first = result.blockers.first().cloned().unwrap_or_else(|| {
                    json!({ "code": "review_blocked", "message": "review checkpoint is blocked" })
                });
                let code = first["code"].as_str().unwrap_or("review_blocked");
                let code = match code {
                    "review_missing" => "review_missing",
                    "review_stale_contract" => "review_stale_contract",
                    "review_stale_changes" => "review_stale_changes",
                    "review_invalid" => "review_invalid",
                    _ => "review_blocked",
                };
                if args.json {
                    print_failure(
                        code,
                        first["message"]
                            .as_str()
                            .unwrap_or("review checkpoint is blocked"),
                        json!({ "blockers": result.blockers, "consumed": result.consumed }),
                    );
                } else {
                    eprintln!(
                        "error: {}",
                        first["message"]
                            .as_str()
                            .unwrap_or("review checkpoint is blocked")
                    );
                }
                std::process::exit(4);
            }
        }
    }
}

fn with_repository<T>(operation: impl FnOnce(&Path) -> Result<T>) -> Result<T> {
    let repository = current_repository()?;
    with_locked_repository(&repository, operation)
}

fn with_locked_repository<T>(
    repository: &Path,
    operation: impl FnOnce(&Path) -> Result<T>,
) -> Result<T> {
    let repository = repository.canonicalize()?;
    let _lock = crate::review_lock::ProjectLock::acquire(&repository)?;
    operation(&repository)
}

fn current_repository() -> Result<PathBuf> {
    let cwd = std::env::current_dir()?;
    crate::review_checkpoints::repository_for(&cwd)
}

fn finish(result: Result<Value>, json: bool) -> Result<()> {
    match result {
        Ok(value) => {
            if json {
                print_success(value)
            } else {
                println!("{}", serde_json::to_string_pretty(&value)?);
                Ok(())
            }
        }
        Err(error) => report_review_error(&error, json),
    }
}

fn report_review_error(error: &anyhow::Error, json: bool) -> Result<()> {
    if let Some((code, exit_code, message, details)) = review_gates::failure_details(error) {
        if json {
            print_failure(code, message, details.clone());
        } else {
            eprintln!("error: {message}");
        }
        std::process::exit(exit_code);
    }
    report_error(&InternalError(error.to_string()), json)
}

fn with_binding_repository<T>(
    subject: &str,
    binding: &str,
    operation: impl FnOnce(&Path) -> Result<T>,
) -> Result<T> {
    let parent = current_repository()?;
    let worker = crate::review_worktrees::worktree_for(&parent, subject, binding)?;
    with_worktree_repository(&parent, worker.as_deref(), operation)
}
fn with_worktree_repository<T>(
    parent: &Path,
    worker: Option<&Path>,
    operation: impl FnOnce(&Path) -> Result<T>,
) -> Result<T> {
    let parent = parent.canonicalize()?;
    let mut roots = vec![parent.clone()];
    if let Some(worker) = worker {
        roots.push(worker.canonicalize()?);
    }
    roots.sort();
    roots.dedup();
    let _locks = roots
        .iter()
        .map(|root| {
            if root == &parent {
                crate::review_lock::ProjectLock::acquire(root)
            } else {
                crate::review_lock::ProjectLock::acquire_worktree(root)
            }
        })
        .collect::<Result<Vec<_>>>()?;
    operation(&parent)
}
