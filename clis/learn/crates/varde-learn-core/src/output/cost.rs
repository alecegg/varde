//! Cost and token totals read from the captured harness traces.

use std::{fs, path::Path};

use serde_json::{Value, json};

use super::OutputHarness;

pub(super) fn collect(harness: OutputHarness, evaluated_trace: &Path, judge_trace: &Path) -> Value {
    let evaluated = read_usage(harness, evaluated_trace);
    let judge = read_usage(harness, judge_trace);
    json!({
        "evaluated": evaluated.cost.map_or(Value::String("unavailable".into()), Value::from),
        "judge": judge.cost.map_or(Value::String("unavailable".into()), Value::from),
        "tokens": {
            "evaluated": evaluated.tokens.map_or(Value::String("unavailable".into()), Value::from),
            "judge": judge.tokens.map_or(Value::String("unavailable".into()), Value::from),
        }
    })
}

#[derive(Default)]
struct Usage {
    cost: Option<f64>,
    tokens: Option<u64>,
}

fn read_usage(harness: OutputHarness, path: &Path) -> Usage {
    let Ok(trace) = fs::read_to_string(path) else {
        return Usage::default();
    };
    let events: Vec<Value> = match harness {
        OutputHarness::Claude => serde_json::from_str::<Value>(&trace)
            .ok()
            .into_iter()
            .collect(),
        OutputHarness::Codex => trace
            .lines()
            .filter_map(|line| serde_json::from_str::<Value>(line).ok())
            .collect(),
    };
    events
        .into_iter()
        .fold(Usage::default(), |mut found, event| {
            let usage = event.get("usage");
            found.cost = event
                .get("total_cost_usd")
                .or_else(|| event.get("cost_usd"))
                .or_else(|| usage.and_then(|value| value.get("total_cost_usd")))
                .or_else(|| usage.and_then(|value| value.get("cost_usd")))
                .and_then(Value::as_f64)
                .or(found.cost);
            found.tokens = usage
                .and_then(|value| value.get("total_tokens").and_then(Value::as_u64))
                .or_else(|| {
                    let usage = usage?;
                    let input = usage.get("input_tokens").and_then(Value::as_u64);
                    let output = usage
                        .get("output_tokens")
                        .and_then(Value::as_u64)
                        .unwrap_or(0);
                    input
                        .map(|input| input.saturating_add(output))
                        .or_else(|| usage.get("output_tokens").and_then(Value::as_u64))
                })
                .or(found.tokens);
            found
        })
}
