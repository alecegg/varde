---
type: reference
title: "Personal/Project Vault layering and merge-at-recall"
---

# Personal Vault / Project Vault layering

How `varde-workflow` layers the Personal Vault and the Project Vault at
recall time. Terminology follows `knowledge/definition/personal-vault` and
`knowledge/definition/project-vault`; the Project-Vault-wins precedence
rule is authoritative in `knowledge/decision/bundle-merge-precedence`.

## Personal Vault

- **Fixed location**: `~/.varde-workflow/`, resolved from the user's home
  directory. There is no flag or configuration to change it.
- **Shape**: a plain Knowledge Bundle, identical to any Project Vault —
  its own `index.md`, the same `.md`-per-Concept layout, the same OKF
  rules.
- **Missing directory**: treated as silently empty. When
  `~/.varde-workflow/` does not exist, all commands behave exactly as if
  no Personal Vault were configured — no error, no initialization step
  required.

## concept list

`concept list --bundle <project-path>` merges Concepts from both vaults
into a single listing, sorted by slug:

- every Concept in the Project Vault (the `--bundle` directory), and
- every Concept in the Personal Vault `~/.varde-workflow/`.

When the same slug exists in both vaults, only the Project Vault's entry
appears — the Project Vault wins same-slug collisions (per
`knowledge/decision/bundle-merge-precedence`).

## Filtering with --vault and --bundle

`concept list --vault <personal|project>` narrows the listing to one
vault; without `--vault` the default merge above applies. `--vault` and
`--bundle` compose with a fixed precedence order: the vault selection
narrows first, then the bundle path filters within the selected vault.
When `--bundle` is combined with `--vault`, the vault selection narrows
first, then the bundle path filters to a subdirectory within the selected
vault — with `--vault project`, `--bundle <path>` lists only concepts
under `<path>` (typically a subdirectory of the project root); with
`--vault personal` a relative `--bundle <path>` filters within the fixed
Personal Vault root (an absolute path has no additional effect). With
neither flag, `--bundle` alone keeps today's behavior: the merged listing
with `--bundle` naming the Project Vault.

## concept show

`concept show <slug> --bundle <project-path>` reads the Project Vault
first:

- slug found in the Project Vault → that Concept is shown; the Personal
  Vault is not consulted;
- slug not found in the Project Vault → falls back to
  `~/.varde-workflow/` and shows the Personal Vault's Concept if present;
- slug found in neither vault → the existing not-found error.

## Scope of merging

- `--bundle`'s meaning is unchanged: it always names the Project Vault.
- Merging applies to `concept list`, `concept show`, and `varde-workflow
  lint` (see `knowledge/reference/bundle-lint`); `lint --vault`/`--bundle`
  narrow it the same way.
- `concept create`, `concept update`, and `concept delete` are unaffected
  by merging: they remain single-vault operations against the explicit
  `--bundle` directory and never consult the Personal Vault.
