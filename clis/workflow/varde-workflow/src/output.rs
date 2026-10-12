//! Stable machine-readable output for every CLI command.

use anyhow::Result;
use serde_json::{Value, json};

/// Fix guidance attached to a command failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Fix {
    NoCommand(String),
}

impl Fix {
    pub fn no_command(reason: impl Into<String>) -> Self {
        Self::NoCommand(reason.into())
    }

    pub fn as_value(&self) -> Value {
        match self {
            Self::NoCommand(reason) => json!({ "reason": reason }),
        }
    }

    pub fn text(&self) -> String {
        match self {
            Self::NoCommand(reason) => reason.clone(),
        }
    }
}

struct FixRule {
    code: &'static str,
    reason: &'static str,
}

const FIX_RULES: &[FixRule] = &[
    FixRule {
        code: "review_invalid",
        reason: "Correct the review report or the merged commit named in the error, then rerun plan conclude.",
    },
    FixRule {
        code: "unreadable_task",
        reason: "Correct the task or plan ownership metadata named in the error.",
    },
    FixRule {
        code: "git_error",
        reason: "Repair Git input or restore the unavailable object described in the error.",
    },
    FixRule {
        code: "internal",
        reason: "Inspect the reported failure and correct the unavailable input or state before retrying.",
    },
    FixRule {
        code: "ownership_stray",
        reason: "Add each stray path to the task's `owns:` or the plan's `shared:`, then rerun check-task-ownership.",
    },
    FixRule {
        code: "ownership_invalid",
        reason: "Correct invalid paths or ownership declarations, then rerun plan validate and check-task-ownership.",
    },
];

pub fn for_code(code: &str) -> Fix {
    let Some(rule) = FIX_RULES.iter().find(|rule| rule.code == code) else {
        return Fix::no_command(format!(
            "no fix guidance is registered for error code `{code}`"
        ));
    };
    Fix::no_command(rule.reason)
}

pub fn page_bounds(total: usize, offset: usize, limit: usize, all: bool) -> (usize, usize) {
    let start = offset.min(total);
    let end = if all {
        total
    } else {
        start.saturating_add(limit).min(total)
    };
    (start, end)
}

pub fn pagination_meta(total: usize, start: usize, end: usize, limit: usize, all: bool) -> Value {
    json!({
        "truncated": end < total,
        "pagination": {
            "total": total,
            "returned": end.saturating_sub(start),
            "offset": start,
            "limit": if all { Value::Null } else { json!(limit) },
            "truncated": end < total,
            "next_offset": if end < total { json!(end) } else { Value::Null },
        }
    })
}

pub fn print_success(data: Value) -> Result<()> {
    print_success_with_meta(data, json!({ "truncated": false }))
}

pub fn print_success_with_meta(data: Value, meta: Value) -> Result<()> {
    println!("{}", varde_core::envelope::success(data, meta,));
    Ok(())
}

pub fn print_error(code: &str, message: String) {
    eprintln!("{}", varde_core::envelope::tool_error(code, &message));
}

pub fn print_error_with_fix(code: &str, message: &str, fix: &Fix) {
    let mut envelope = varde_core::envelope::tool_error(code, message);
    envelope["data"]["error"]["fix"] = fix.as_value();
    eprintln!("{envelope}");
}

pub fn print_failure(code: &str, message: &str, details: Value) {
    let (details, fix) = take_fix(details);
    let mut envelope = varde_core::envelope::negative_result(
        code,
        message,
        details,
        json!({ "truncated": false }),
    );
    if let Some(fix) = fix {
        envelope["data"]["error"]["fix"] = fix;
    }
    println!("{envelope}");
}

pub fn print_failure_with_meta(code: &str, message: &str, details: Value, meta: Value) {
    println!(
        "{}",
        varde_core::envelope::negative_result(code, message, details, meta)
    );
}

pub fn print_failure_with_fix(code: &str, message: &str, details: Value, fix: &Fix) {
    let (details, embedded_fix) = take_fix(details);
    let mut envelope = varde_core::envelope::negative_result(
        code,
        message,
        details,
        json!({ "truncated": false }),
    );
    envelope["data"]["error"]["fix"] = embedded_fix.unwrap_or_else(|| fix.as_value());
    println!("{envelope}");
}

fn take_fix(mut details: Value) -> (Value, Option<Value>) {
    let fix = details
        .as_object_mut()
        .and_then(|details| details.remove("fix"));
    let fix = fix.or_else(|| {
        details["blockers"][0]["fix"]
            .as_object()
            .map(|_| details["blockers"][0]["fix"].clone())
    });
    (details, fix)
}
