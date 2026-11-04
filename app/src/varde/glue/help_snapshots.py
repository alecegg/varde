# The snapshot literals must retain exact CLI output for regression comparisons.
# ruff: noqa: E501, RUF100
"""App help text snapshots."""

SEARCH_HELP = "Search code, docs, knowledge, plans, captured output and friction\n\nUsage: varde search [OPTIONS] <query>\n\nArguments:\n  <query>  Text to search for\n\nOptions:\n      --in <in>        Sources to search, comma separated [default: all] [possible values: code, docs, knowledge, plans, output, friction]\n      --limit <limit>  Most hits per source [default: 5]\n      --json           Print the machine-output envelope\n  -h, --help           Print help\n"
EDIT_HELP = "Preview and apply AST edits\n\nUsage: varde edit <COMMAND>\n\nCommands:\n  preview  Build a rewrite proposal without changing source files\n  apply    Apply a saved proposal after validating its source snapshots\n  help     Print this message or the help of the given subcommand(s)\n\nOptions:\n  -h, --help  Print help\n"
HOOK_SESSION_START_HELP = "Usage: varde hook session-start --harness <claude|codex|opencode|pi>\n\nOptions:\n  --harness <HARNESS>  Harness the hook runs for (required)\n  -h, --help           Print help\n"
HOOK_USER_PROMPT_SUBMIT_HELP = "Usage: varde hook user-prompt-submit --harness <claude|codex|opencode|pi>\n\nOptions:\n  --harness <HARNESS>  Harness the hook runs for (required)\n  -h, --help           Print help\n"
HOOK_POST_TOOL_USE_HELP = "Usage: varde hook post-tool-use --harness <claude|codex|opencode|pi>\n\nOptions:\n  --harness <HARNESS>  Harness the hook runs for (required)\n  -h, --help           Print help\n"
HOOK_STOP_HELP = "Usage: varde hook stop --harness <claude|codex|opencode|pi>\n\nOptions:\n  --harness <HARNESS>  Harness the hook runs for (required)\n  -h, --help           Print help\n"
HOOK_SUBAGENT_START_HELP = "Usage: varde hook subagent-start --harness <claude|codex>\n\nOptions:\n  --harness <HARNESS>  Harness the hook runs for (required)\n  -h, --help           Print help\n"
HOOK_PRE_TOOL_USE_HELP = "Usage: varde hook pre-tool-use --harness <claude|codex>\n\nOptions:\n  --harness <HARNESS>  Harness the hook runs for (required)\n  -h, --help           Print help\n"
