# Baseline example problems

Four problems, each with `prompt.txt` (one sentence), `spec.md` (at most 8 language-neutral cases), `api.md` (names per language) and per-language tests. `reference-stub/` holds a tiny implementation used only to prove the tests run; stubs are tests-only fixtures and are never baselines. `toolchains.toml` records the test command and toolchain per language. Validate with `uv run python code/bench/quality-corpus/tools/baseline_problems.py --check ...`.
