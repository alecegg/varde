use varde_workflow_core::memory::{
    Config, DEFAULT_WAKE_MAX_FAILURES, DEFAULT_WAKE_TIMEOUT_SECONDS,
};

fn config(source: &str) -> Config {
    toml::from_str(source).expect("config should deserialize leniently")
}

#[test]
fn wake_settings_have_defaults() {
    let orchestration = Config::default().orchestration;
    assert_eq!(orchestration.wake_command(), (Vec::new(), None));
    assert_eq!(
        orchestration.wake_timeout_seconds(),
        (DEFAULT_WAKE_TIMEOUT_SECONDS, None)
    );
    assert_eq!(
        orchestration.wake_max_failures(),
        (DEFAULT_WAKE_MAX_FAILURES, None)
    );
}

#[test]
fn wake_settings_parse_valid_user_config() {
    let cfg = config(
        "[orchestration]\nwake_command = [\"agent\", \"resume\"]\nwake_timeout_seconds = 25\nwake_max_failures = 5\n",
    );
    assert_eq!(
        cfg.orchestration.wake_command(),
        (vec!["agent".to_string(), "resume".to_string()], None)
    );
    assert_eq!(cfg.orchestration.wake_timeout_seconds(), (25, None));
    assert_eq!(cfg.orchestration.wake_max_failures(), (5, None));
}

#[test]
fn invalid_wake_settings_fall_back_with_reasons() {
    for bad in ["0", "-2", "\"soon\"", "1.5"] {
        let cfg = config(&format!("[orchestration]\nwake_timeout_seconds = {bad}\n"));
        let (value, reason) = cfg.orchestration.wake_timeout_seconds();
        assert_eq!(value, DEFAULT_WAKE_TIMEOUT_SECONDS, "{bad}");
        assert!(reason.is_some(), "{bad}");

        let cfg = config(&format!("[orchestration]\nwake_max_failures = {bad}\n"));
        let (value, reason) = cfg.orchestration.wake_max_failures();
        assert_eq!(value, DEFAULT_WAKE_MAX_FAILURES, "{bad}");
        assert!(reason.is_some(), "{bad}");
    }

    let cfg = config("[orchestration]\nwake_command = [\"agent\", 2]\n");
    let (command, reason) = cfg.orchestration.wake_command();
    assert!(command.is_empty());
    assert!(reason.is_some());
}

#[test]
fn non_array_wake_command_falls_back_with_reason() {
    let cfg = config("[orchestration]\nwake_command = \"agent resume\"\n");
    let (command, reason) = cfg.orchestration.wake_command();
    assert!(command.is_empty());
    assert!(reason.is_some());
}
