// SPDX-License-Identifier: MIT

fn suggest_custom_arg_value() {
    fn custom_completer() -> Vec<CompletionCandidate> {
        vec![
            CompletionCandidate::new("custom1"),
            CompletionCandidate::new("custom2"),
            CompletionCandidate::new("custom3"),
        ]
    }

    let mut cmd = Command::new("dynamic").arg(
        clap::Arg::new("custom")
            .long("custom")
            .add(ArgValueCandidates::new(custom_completer)),
    );

    assert_data_eq!(
        complete!(cmd, "--custom [TAB]"),
        snapbox::str![[r#"
custom1
custom2
custom3
"#]],
    );
}