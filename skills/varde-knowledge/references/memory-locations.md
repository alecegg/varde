# Memory locations

References in this skill write memory paths as `<working>/…` (plans, handoffs,
reviews, prototypes, friction — local, never committed) and `<knowledge>/…` (durable
notes, specs, contracts — committed with the project). Resolve both once per
session, before the first read or write, and reuse the result:

1. If `command -v varde-workflow >/dev/null 2>&1` succeeds, run
   `varde-workflow paths --json` from the project root. `data.working` and
   `data.knowledge` are absolute directories; `data.*_source` says whether
   each came from `env`, a per-`project` setting, the user's `default`, or the
   `builtin` layout.
2. Otherwise: `<working>` is `$VARDE_WORKING_DIR` when set, else
   `memory-bank/working`; `<knowledge>` is `$VARDE_KNOWLEDGE_DIR` when set,
   else `memory-bank/knowledge`.

Both default to the project tree. A user redirects either one — for one
project or for every project — with
`varde-workflow paths set [--project <root> | --default] --working <dir> --knowledge <dir>`.
The setting lives in `~/.config/varde/paths.toml`, outside every repository,
so it never enters git history.

When a directory is redirected outside the repository, git-based checks on its
contents (`git check-ignore`, `git mv`, `git status`) do not apply; use plain
filesystem operations there and treat the location as already local-only.
