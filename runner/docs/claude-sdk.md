# Claude Agent SDK

This adapter runs Anthropic's Claude Agent SDK in the runner's Node host.

- It is expected to use Claude Code's local login for the runner's OS account.
  Headless login refresh has not been verified; the smoke below checks it.
- Sign in before launch; the runner does not create or store credentials.
- See Anthropic's [Claude Code authentication guide](https://docs.anthropic.com/en/docs/claude-code/getting-started).

The runner removes these variables from the SDK child environment:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`
- `CLAUDE_CODE_OAUTH_TOKEN`

## Enable the adapter

Use Node.js 22.19 or newer. Until the separate native-cutover c2 defaults
change lands, enable the adapter and select it with an explicit type in
`runner.toml`:

```toml
[claude_sdk]
enabled = true
stream_idle_timeout_s = 300

[types.claude]
harness = "claude-sdk"
model = "claude-sonnet-5-5"
reasoning_effort = "medium"
mode = "workspace-write"

[roles.builder]
type = "claude"
```

`stream_idle_timeout_s` flags a quiet stream without stopping it. This docs
change does not alter configuration defaults. Native-cutover c2 owns the
defaults change:

- `claude-sdk` becomes the default Claude route.
- The guard role stays on its existing route.
- `claude-cli` remains registered but disabled unless explicitly enabled.

## Terms

Anthropic's [SDK README](https://github.com/anthropics/claude-agent-sdk-typescript#license-and-terms)
says the package is governed by Commercial Terms; review [the current SDK plan
terms](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
before relying on subscription access.
The findings note is [in `~/source/agent-memory`](../../../../../../source/agent-memory/projects/varde-py/working/plans/2026-10-25-claude-sdk-adapter/notes/terms-findings-2026-10-25.md).

## Post-flip real-login smoke

After native-cutover c2 changes the defaults, run this checklist. It is a
post-flip check, not a gate. Record results in the adapter plan's Progress.

- [ ] With the runner stopped, confirm Claude Code is signed in as the same OS
  user that will run it. Do not add credentials to `runner.toml` or prompts.
- [ ] Start the runner and launch a planner in a disposable workspace without
  specifying a harness. Confirm the session uses `claude-sdk` and answers.
- [ ] Send a follow-up prompt and confirm the same session responds.
- [ ] Request one harmless workspace write.
- [ ] Approve it through the runner and confirm the write completes once.
- [ ] Restart the runner, then send another prompt to the existing session.
  Confirm the session resumes and responds.
- [ ] Stop and archive the session. Confirm it ends cleanly and no Claude
  child process remains.

Smoke result: `PENDING`  
Date / OS / runner commit:  
Notes:
