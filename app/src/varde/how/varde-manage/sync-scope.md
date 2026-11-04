---
topic: varde-manage/sync-scope
version: 1
summary: Sync scope table and OpenCode notes, part 2 of 3, apply only after approval in sync-workflow
---

## Sync scope

| Scope | Action |
|---|---|
| Default or harness setup | Run the reviewed `varde setup sync` invocation. |
| Skill subset or preset | Add `--skills` or `--preset`; flags combine for that run. Add `--save` to make them defaults. `--skills all` selects every skill for that run. |
| Harness hooks | Run `varde setup hooks install --harness <h>` per requested harness; hooks do not install the skill. |

- OpenCode 2.x hook and agent support starts at 2.0.18. Older 2.x releases warn
  and continue best effort.
- OpenCode 1.x keeps its legacy formats. Sync and hook install honor
  `XDG_CONFIG_HOME`. Install channels are in `varde setup hooks install --help`.
