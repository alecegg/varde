//! Repeated-run aggregation for the candidate and current arms.

use serde_json::{Value, json};

use super::run::RunRecord;

const MIN_COMPARISON_RUNS: usize = 3;

pub(super) fn summarize(records: &[RunRecord]) -> Value {
    let runs: Vec<Value> = records
        .iter()
        .map(|record| {
            json!({
                "eval_id": record.eval_id,
                "config": record.config.as_str(),
                "run": record.run,
                "status": record_status(record),
                "cost": record.cost,
                "assertions": record.assertions,
            })
        })
        .collect();
    let cases: Vec<Value> = records
        .iter()
        .map(|record| record.eval_id.as_str())
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .map(|eval_id| {
            let current = summarize_arm(records, eval_id, false);
            let candidate = summarize_arm(records, eval_id, true);
            json!({
                "eval_id": eval_id,
                "current": current,
                "candidate": candidate,
            })
        })
        .collect();
    let (included, inconclusive) = counts(records);
    let comparison = included.iter().all(|count| *count >= MIN_COMPARISON_RUNS);
    let status = records
        .iter()
        .map(record_status)
        .max_by_key(|status| status_rank(status))
        .unwrap_or("inconclusive");
    let costs = cost_totals(records);
    let outcomes: Vec<f64> = records
        .iter()
        .filter_map(|record| match record_status(record) {
            "pass" => Some(1.0),
            "fail" => Some(0.0),
            _ => None,
        })
        .collect();
    let overall_variance = variance(&outcomes, &mean(&outcomes));

    json!({
        "status": status,
        "evidence": if comparison { "comparison" } else { "screen" },
        "variance": overall_variance,
        "minimum_runs_per_arm": MIN_COMPARISON_RUNS,
        "included_runs": {"current": included[0], "candidate": included[1]},
        "inconclusive_runs": {"current": inconclusive[0], "candidate": inconclusive[1]},
        "cost": total_costs(records),
        "cost_by_arm": costs,
        "runs": runs,
        "cases": cases,
    })
}

fn summarize_arm(records: &[RunRecord], eval_id: &str, with_skill: bool) -> Value {
    let runs: Vec<_> = records
        .iter()
        .filter(|record| {
            record.eval_id == eval_id && (record.config.as_str() == "with_skill") == with_skill
        })
        .collect();
    let eligible: Vec<f64> = runs
        .iter()
        .filter_map(|record| match record_status(record) {
            "pass" => Some(1.0),
            "fail" => Some(0.0),
            _ => None,
        })
        .collect();
    let pass_rate = mean(&eligible);
    let variance = variance(&eligible, &pass_rate);
    let inconclusive = runs.len() - eligible.len();
    json!({
        "runs": runs.len(),
        "included_runs": eligible.len(),
        "inconclusive_runs": inconclusive,
        "pass_rate": pass_rate,
        "variance": variance,
        "assertion_pass_rate": mean(&runs.iter().filter_map(|run| {
            (record_status(run) != "inconclusive").then_some(run.pass_rate).flatten()
        }).collect::<Vec<_>>()),
    })
}

fn counts(records: &[RunRecord]) -> ([usize; 2], [usize; 2]) {
    let mut included = [0; 2];
    let mut inconclusive = [0; 2];
    for record in records {
        let arm = usize::from(record.config.as_str() == "with_skill");
        if record_status(record) == "inconclusive" {
            inconclusive[arm] += 1;
        } else {
            included[arm] += 1;
        }
    }
    (included, inconclusive)
}

fn cost_totals(records: &[RunRecord]) -> Value {
    let mut costs = [[0.0; 2]; 2];
    let mut tokens = [[0_u64; 2]; 2];
    let mut cost_runs = [[0; 2]; 2];
    let mut token_runs = [[0; 2]; 2];
    for record in records {
        let arm = usize::from(record.config.as_str() == "with_skill");
        for (index, key) in ["evaluated", "judge"].into_iter().enumerate() {
            if let Some(cost) = record.cost.get(key).and_then(Value::as_f64) {
                costs[arm][index] += cost;
                cost_runs[arm][index] += 1;
            }
            if let Some(count) = record.cost["tokens"].get(key).and_then(Value::as_u64) {
                tokens[arm][index] += count;
                token_runs[arm][index] += 1;
            }
        }
    }
    json!({
        "current": cost_arm(costs[0], tokens[0], cost_runs[0], token_runs[0]),
        "candidate": cost_arm(costs[1], tokens[1], cost_runs[1], token_runs[1]),
    })
}

fn total_costs(records: &[RunRecord]) -> Value {
    let mut costs = [0.0; 2];
    let mut measured = [0; 2];
    for record in records {
        for (index, key) in ["evaluated", "judge"].into_iter().enumerate() {
            if let Some(cost) = record.cost.get(key).and_then(Value::as_f64) {
                costs[index] += cost;
                measured[index] += 1;
            }
        }
    }
    json!({
        "evaluated": amount(costs[0], measured[0]),
        "judge": amount(costs[1], measured[1]),
    })
}

fn cost_arm(
    costs: [f64; 2],
    tokens: [u64; 2],
    cost_runs: [usize; 2],
    token_runs: [usize; 2],
) -> Value {
    json!({
        "evaluated": amount(costs[0], cost_runs[0]),
        "judge": amount(costs[1], cost_runs[1]),
        "tokens": {
            "evaluated": token_amount(tokens[0], token_runs[0]),
            "judge": token_amount(tokens[1], token_runs[1]),
        },
        "measured_runs": {"evaluated": cost_runs[0], "judge": cost_runs[1]},
        "measured_token_runs": {"evaluated": token_runs[0], "judge": token_runs[1]},
    })
}

fn amount(total: f64, runs: usize) -> Value {
    if runs == 0 {
        json!("unavailable")
    } else {
        json!(round4(total))
    }
}

fn token_amount(total: u64, runs: usize) -> Value {
    if runs == 0 {
        json!("unavailable")
    } else {
        json!(total)
    }
}

fn mean(values: &[f64]) -> Value {
    if values.is_empty() {
        Value::Null
    } else {
        json!(round4(values.iter().sum::<f64>() / values.len() as f64))
    }
}

fn variance(values: &[f64], mean: &Value) -> Value {
    if values.is_empty() {
        Value::Null
    } else {
        let mean = mean.as_f64().unwrap_or_default();
        json!(round4(
            values
                .iter()
                .map(|value| (value - mean).powi(2))
                .sum::<f64>()
                / values.len() as f64
        ))
    }
}

fn round4(value: f64) -> f64 {
    (value * 10_000.0).round() / 10_000.0
}

fn record_status(record: &RunRecord) -> &'static str {
    if record.blocked || record.total_assertions == 0 {
        "inconclusive"
    } else if record.outcome != super::EvalOutcome::Completed
        || record.passed_assertions != record.total_assertions
    {
        "fail"
    } else {
        "pass"
    }
}

fn status_rank(status: &&str) -> u8 {
    match *status {
        "fail" => 2,
        "inconclusive" => 1,
        _ => 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::output::{Config, EvalOutcome};
    use std::path::PathBuf;

    fn record(outcome: EvalOutcome, blocked: bool, total: u32, passed: u32) -> RunRecord {
        RunRecord {
            eval_id: "eval".into(),
            config: Config::WithoutSkill,
            run: 1,
            run_dir: PathBuf::new(),
            outcome,
            judge_outcome: "not_needed",
            total_assertions: total,
            passed_assertions: passed,
            pass_rate: (total > 0).then_some(passed as f64 / total as f64),
            duration_ms: 0,
            measured_tokens: None,
            cost_usd: None,
            blocked,
            assertions: Vec::new(),
            cost: json!({}),
            redacted: 0,
        }
    }

    #[test]
    fn real_failure_outranks_blocked_inconclusive_run() {
        let result = summarize(&[
            record(EvalOutcome::Failed, false, 1, 0),
            record(EvalOutcome::Completed, true, 1, 1),
        ]);
        assert_eq!(result["status"], "fail");
        assert_eq!(result["inconclusive_runs"]["current"], 1);
    }
}
