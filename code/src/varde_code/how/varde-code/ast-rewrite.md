---
topic: varde-code/ast-rewrite
version: 1
summary: Preview an AST rewrite from a rules file or an inline rule, then apply its proposal
---

Preview from one rules file or one inline rule, then apply its proposal:

```sh
varde edit preview --rules rules.json --path src/ --json
varde edit preview --language typescript --pattern 'oldCall($ARG)' --replacement 'newCall($ARG)' --path src/ --json
varde edit apply --proposal <data.proposal_path> --json
```

Use `varde edit preview --help` and `varde edit apply --help` for proposal fields and command inputs. Preview before applying, then review the diff.
