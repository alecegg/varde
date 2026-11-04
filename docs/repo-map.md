# Repo map

The repo map is a set of committed markdown files under `docs/repo-map/` that
orient an agent (or a person) before it explores the code.

- `docs/repo-map/README.md` is the top-level map of the repo.
- `docs/repo-map/modules/<slug>.md` is a pack for one folder.
- `docs/repo-map/modules.txt` lists the folders that get a pack, one per line.
- `docs/repo-map/exclude.txt` lists paths left out of the map.

Packs are plain markdown. You can read them without varde. Each records the
commit it was built from, so varde can tell when it is stale.

## Commands

- `varde map packs build --all` writes the README and a pack for every folder in `modules.txt`.
- `varde map packs build --stale` writes only missing or stale packs and prints `packs fresh` when nothing changed.
- `varde map packs build [FOLDER]` writes one folder's pack; with no folder it writes the README.
- `varde map packs status --check` exits 1 when any pack is stale or the README is missing.

`build` refuses in a linked git worktree (it has no index). Run it from the main checkout.

## Recommended refresh points

Refresh packs at exactly two points and nowhere else:

1. At plan end, after merging to main, run `varde map packs build --stale` and commit `docs/repo-map/`. This repo wraps it as `just repo-map-refresh`.
2. At PR create, refresh the packs before publishing the PR.

Why only these two:

- Diffs stay small and representative. Packs change once per finished unit of work, not on every edit.
- Branches do not conflict on packs. Only these steps write them, so feature branches never touch `docs/repo-map/` in parallel.
