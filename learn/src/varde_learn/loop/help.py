"""Committed Rust help snapshots for learn commands."""

from __future__ import annotations

from importlib.resources import files

_HELP_FILES = {
    "learn": "help/learn.txt",
    "friction": "help/friction.txt",
    "friction list": "help/friction/list.txt",
    "friction add": "help/friction/add.txt",
    "friction show": "help/friction/show.txt",
    "friction set-status": "help/friction/set-status.txt",
    "friction export": "help/friction/export.txt",
    "friction import": "help/friction/import.txt",
    "adopt": "help/adopt.txt",
    "adopt record": "help/adopt/record.txt",
    "adopt recurrence": "help/adopt/recurrence.txt",
    "sweep": "help/sweep.txt",
    "run": "help/run.txt",
    "skills demand": "help/skills-demand.txt",
    **{
        f"skills {verb}": f"help/skills-{verb}.txt"
        for verb in (
            "candidates",
            "extract",
            "reset",
            "accept",
            "fill",
            "reject",
            "report",
            "updates",
        )
    },
    "memory": "help/memory.txt",
    **{
        f"memory {verb}": f"help/memory-{verb}.txt"
        for verb in (
            "add",
            "list",
            "show",
            "retire",
            "reset",
            "surface",
            "promote",
            "pull",
            "migrate",
        )
    },
}

_ENTRY_VERBS = ("search", "update", "set-field", "delete", "map", "lint")

_HELP_TEXT = {
    "learn": (
        "Diagnose sessions, measure skills, record friction, and measure CLI "
        "guardrails\n\n"
        "Usage: varde learn <COMMAND>\n\nCommands:\n"
        "  sessions   Inspect, summarize, sweep and review local agent sessions\n"
        "  measure    Measure a skill: flow, ledger, baseline, trigger, output, "
        "calibration\n"
        "  check      Check skill and document Markdown: lint, frontmatter, FLOW.md, "
        "blocks\n"
        "  how        Print a how-topic for a skill, or list its topics\n"
        "  docs       Serve, comment on and recap documents; spec inventory\n"
        "  friction   Read and maintain the global friction store; adopt changes\n"
        "  knowledge  Create, search and lint the project Knowledge Bundle\n"
        "  memory     Scoped agent, skill, project and global memory entries\n"
        "  skills     Skill demand and the self-improvement loop (candidates, report)\n"
        "  tools      Summarize runner tool calls by agent role\n"
        "  help       Print this message or the help of the given subcommand(s)\n"
    ),
    "sessions": (
        "Inspect, summarize, sweep and review local agent sessions\n\n"
        "Usage: varde learn sessions <COMMAND>\n\nCommands:\n"
        "  show [SESSION]  List recent sessions, or inspect one session or bundle\n"
        "  summary         Session metrics and cross-session waste patterns\n"
        "  capture         Record one verified incident\n"
        "  sweep           Analyze new local agent sessions\n"
        "  run             Review sessions in a time window\n"
        "  calls           Command failures and retries, plus guardrail firing counts\n"
        "  fire            Record an explicit guardrail firing\n"
    ),
    "measure": (
        "Measure a skill\n\nUsage: varde learn measure <SKILL> <KIND> [OPTIONS]\n\n"
        "Kinds (free):\n"
        "  flow       Routes, token costs, structure and findings of a skill\n"
        "  ledger     Validate, check and score a decision ledger "
        "(--ledger FILE; --write rehashes)\n"
        "  baseline   Slim baseline, gap fills and drift (--baselines DIR)\n\n"
        "Kinds (billed; run only when named):\n"
        "  trigger    Trigger accuracy of a description\n"
        "  output     Skill-guided output quality\n"
        "  calibrate  Whether declared mutations fail the evals\n"
    ),
    "skills": (
        "Skill demand and the self-improvement loop\n\n"
        "Usage: varde learn skills <COMMAND>\n\nCommands:\n"
        "  demand [SKILL]        How-topic requests, friction and fills per skill\n"
        "  candidates            Rank skills and agents to trim, add to or reset\n"
        "  extract SKILL [STEP]  Propose moving a step into a counted tool\n"
        "  reset SKILL           Propose slimming a skill or restoring its baseline\n"
        "  accept ID             Apply a stored proposal\n"
        "  fill SKILL            Record or retire a baseline gap fill\n"
        "  reject ID             Mark a proposal rejected; changes no file\n"
        "  report                List loop records and write the report page\n"
        "  updates [SKILL]       Show modified skills; diff to the packaged copy\n"
    ),
    "sessions calls": (
        "Summarize command failures and retries, then list registered guardrails "
        "with fired/blocked counts (`--dead` lists only guardrails with no firing "
        "in the window; default window 30d for guardrails).\n\n"
        "Usage: varde learn sessions calls [OPTIONS]\n\nOptions:\n"
        "      --dead               List only guardrails with no firing in the window\n"
        "      --window <DURATION>  Include calls from the trailing window\n"
        "      --json               Print machine-readable output\n"
        "  -h, --help               Print help\n"
    ),
    "calls": (
        "Summarize command failures and retries. Commands are recorded as a route "
        "plus a validated subcommand when present; outcomes are success, failure, "
        "or blocked. Fastpath, `sessions fire`, `setup watch` and `plan watch` "
        "calls are not recorded. Rows older than the retention window "
        "(`[retention] calls_days` in `sweep.toml`, default 30 days) that this "
        "report has covered are pruned; a longer window warns.\n\n"
        "Usage: varde learn calls [OPTIONS]\n\nOptions:\n"
        "      --window <DURATION>  Include calls from the trailing window "
        "(for example, 30d)\n"
        "      --json               Print machine-readable output\n"
        "  -h, --help               Print help\n"
    ),
    "tools": (
        "Summarize runner tool calls by agent role.\n\n"
        "Usage: varde learn tools --by-role [OPTIONS]\n\n"
        "Options:\n"
        "      --since <DURATION>  Include calls from the trailing window\n"
        "      --friction           Append failure occurrences to the friction store\n"
        "      --json               Print machine-readable output\n"
        "  -h, --help               Print help\n"
    ),
    "guardrails": (
        "List registered guardrails and fired/blocked counts in the trailing "
        "window. Command entries match a route-path prefix.\n\n"
        "Usage: varde learn guardrails [OPTIONS]\n\nOptions:\n"
        "      --dead               List only guardrails with no firing in the window\n"
        "      --window <DURATION>  Trailing window [default: 30d]\n"
        "      --json               Print machine-readable output\n"
        "  -h, --help               Print help\n\nCommands:\n"
        "  fire <ID> [--blocked]  Record an explicit guardrail firing\n"
    ),
    "guardrails fire": (
        "Record an explicit guardrail firing; blocked firings are counted "
        "separately.\n\n"
        "Usage: varde learn sessions fire <ID> [--blocked]\n"
    ),
    "store": (
        "Show or switch where learn data is stored. Migration is one-way; "
        "source files stay until `retire`.\n\n"
        "`prune --domain calls` deletes call rows older than the retention window "
        "and older than the used-through mark that `sessions calls` and "
        "`skills demand` set; `status` shows the used-through mark and oldest "
        "`ts`.\n\n"
        "Usage: varde learn store <status|migrate|verify|retire|prune> "
        "[--domain friction|ledger|calls] [--dry-run] [--json]\n"
        "       varde learn store prune --domain calls [--days N] [--dry-run] "
        "[--vacuum] [--json]\n"
    ),
}


_NEW_TO_OLD = {
    "sessions summary": "diagnose summary",
    "sessions capture": "diagnose capture",
    "sessions show": "diagnose inspect",
    "sessions sweep": "sweep",
    "sessions run": "run",
    "sessions fire": "guardrails fire",
    "friction adopt": "adopt record",
    "friction recurrence": "adopt recurrence",
    "measure trigger": "eval trigger",
    "measure output": "eval output",
    "measure calibrate": "eval calibrate",
}


def _entry_verb_help(verb: str) -> str:
    text = files("varde_learn.loop").joinpath("help/memory_entries.txt").read_text()
    sections = text.split("=== ")[1:]
    return next(
        s.split("\n", 1)[1].strip("\n") + "\n"
        for s in sections
        if s.startswith(verb + "\n")
    )


def help_text(path: str = "") -> str:
    command = " ".join(path.split())
    command = command.removeprefix("learn ")
    command = _NEW_TO_OLD.get(command, command)
    if command in _HELP_TEXT:
        return _HELP_TEXT[command]
    if command.removeprefix("memory ") in _ENTRY_VERBS and command.startswith(
        "memory "
    ):
        return _entry_verb_help(command.removeprefix("memory "))
    if command in _HELP_FILES:
        return files("varde_learn.loop").joinpath(_HELP_FILES[command]).read_text()
    if command in {"", "learn"}:
        return _HELP_TEXT["learn"]
    from .cli_diagnose import help_text as diagnose_help_text

    return diagnose_help_text(command)
