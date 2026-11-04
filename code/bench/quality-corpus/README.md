# Quality corpus

This directory holds pinned, license-verified source repositories for quality-score validation. `corpus/manifest.toml` records each verified pin and its single corpus role; repositories reserved by call-resolution may remain roleless.

## Layout

- `corpus/manifest.toml` lists candidate source repositories, anticipated SPDX identifiers, languages, pins, history cutoffs, and corpus roles. An entry whose upstream moved keeps a `redirected_from` note naming the previous repository. Its `pair_groups` section names samples pairable within a task or a refactor pair for head-to-head ranking.
- `corpus/manifest.py` validates repositories, pair groups, and the manifest's deterministic digest.
- `corpus/fetch.py` fetches verified pins into an external cache and writes temporary source snapshots.
- `corpus/roles.py` checks role separation and calibration conflicts with call-resolution repositories.
- `corpus/ROLE_REASSIGNMENT.md` records the calibration replacements for call-resolution-reserved repositories.
- `tests/corpus/` contains offline tests backed by local bare Git repositories.

`tools/tiers.py --check` validates category-(b) item tiers and profiles. Restricted-store directories for other categories are reported as a note and ignored.

## Fetch

After the manifest entries have verified SPDX licenses, commit pins, cutoffs, and roles, run:

```sh
uv run python code/bench/quality-corpus/corpus/fetch.py
```

Clones are stored under `$VARDE_BENCH_CACHE`; the default is `~/.cache/varde/bench`. Each fetch leaves `FETCH_HEAD` and a local `refs/heads/pinned` ref on the verified pin, so `git log` and `pairs/mine.py` can walk it. Repositories whose roles need ancestry (`history`, `pairs`) fetch full history without blobs and check every history cutoff SHA; `calibration`, `held-out`, and `mutation-base` repositories fetch the pin at `--depth=1`. Snapshot trees are extracted in a temporary directory and removed when the command exits. Fetching is intentionally unavailable for entries still marked `unverified`.

Clones are partial (`--filter=blob:none`), so reading a revision that was not fetched lazily fetches it from the promisor remote and needs the network. Extracting the pinned snapshot during the fetch materializes the pin's tip blobs in the cache, so reading the pin again is offline; any other revision is not.
