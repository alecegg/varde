//! User-wide settings in `config.toml`.

use crate::cli::{ConfigArgs, ConfigCommand, ConfigGetArgs, ConfigSetArgs};
use crate::commands::error::{CliError, InternalError, report_error};
use crate::output::{print_failure, print_success};
use anyhow::Result;
use serde_json::json;
use varde_workflow_core::memory;

const KNOWN_KEYS: &str = "usage_limit";

pub fn run(args: ConfigArgs) -> Result<()> {
    match args.command {
        None => show(args.json),
        Some(ConfigCommand::Get(args)) => get(args),
        Some(ConfigCommand::Set(args)) => set(args),
        Some(ConfigCommand::Unset(args)) => unset(args),
    }
}

fn known_key(key: &str, json: bool) -> Result<bool> {
    if key == KNOWN_KEYS {
        Ok(true)
    } else {
        report_error(
            &CliError(format!(
                "unknown config key `{key}`; known keys: {KNOWN_KEYS}"
            )),
            json,
        )?;
        Ok(false)
    }
}

fn load(json: bool) -> Result<Option<memory::Config>> {
    match memory::load_config() {
        Ok(config) => Ok(Some(config)),
        Err(error) => {
            report_error(&InternalError(error.to_string()), json)?;
            Ok(None)
        }
    }
}

fn warnings(config: &memory::Config) -> Vec<String> {
    config
        .settings
        .unknown
        .keys()
        .map(|key| format!("unknown settings key `{key}`"))
        .collect()
}

fn show(json: bool) -> Result<()> {
    let Some(config) = load(json)? else {
        return Ok(());
    };
    let path = memory::config_path();
    let warnings = warnings(&config);
    if json {
        print_success(json!({
            "config": path,
            "settings": { "usage_limit": config.settings.usage_limit },
            "warnings": warnings,
        }))
    } else {
        println!("config: {}", path.display());
        println!(
            "usage_limit: {}",
            config.settings.usage_limit.as_deref().unwrap_or("(unset)")
        );
        for warning in warnings {
            eprintln!("warning: {warning}");
        }
        Ok(())
    }
}

fn get(args: ConfigGetArgs) -> Result<()> {
    if !known_key(&args.key, args.json)? {
        return Ok(());
    }
    let Some(config) = load(args.json)? else {
        return Ok(());
    };
    let value = config.settings.usage_limit.as_deref();
    if args.json {
        if value.is_none() {
            print_failure(
                "not_set",
                "config key `usage_limit` is not set",
                json!({ "key": args.key, "config": memory::config_path(), "warnings": warnings(&config) }),
            );
            return Ok(());
        }
        print_success(json!({
            "key": args.key,
            "value": value,
            "set": value.is_some(),
            "config": memory::config_path(),
            "warnings": warnings(&config),
        }))
    } else {
        println!("{}", value.unwrap_or("(unset)"));
        for warning in warnings(&config) {
            eprintln!("warning: {warning}");
        }
        Ok(())
    }
}

fn set(args: ConfigSetArgs) -> Result<()> {
    if !known_key(&args.key, args.json)? {
        return Ok(());
    }
    edit(Some(args.value), args.json)
}

fn unset(args: ConfigGetArgs) -> Result<()> {
    if !known_key(&args.key, args.json)? {
        return Ok(());
    }
    edit(None, args.json)
}

fn edit(value: Option<String>, json: bool) -> Result<()> {
    let Some(mut config) = load(json)? else {
        return Ok(());
    };
    config.settings.usage_limit = value;
    match memory::save_config(&config) {
        Ok(path) => {
            if json {
                print_success(json!({
                    "key": KNOWN_KEYS,
                    "value": config.settings.usage_limit,
                    "set": config.settings.usage_limit.is_some(),
                    "config": path,
                    "warnings": warnings(&config),
                }))
            } else {
                println!("updated {}", path.display());
                for warning in warnings(&config) {
                    eprintln!("warning: {warning}");
                }
                Ok(())
            }
        }
        Err(error) => report_error(&InternalError(error.to_string()), json),
    }
}
