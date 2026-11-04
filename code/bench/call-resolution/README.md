# Call-resolution audit

## Running the adapter tests offline

Five tests in `tests/adapters/test_existing_adapter.py` exercise exports from the existing adapter. They need the tree-sitter Python and TypeScript grammars in the language-pack cache. Prefetch them into a cache directory before running those tests:

```sh
export VARDE_TREE_SITTER_CACHE_DIR="$PWD/.tree-sitter-cache"
uv run python -c 'from tree_sitter_language_pack import PackConfig, configure, download; configure(PackConfig(cache_dir=".tree-sitter-cache")); download(["python", "typescript"])'
uv run pytest tests/adapters/test_existing_adapter.py -q
```

The prefetch command may need network access the first time. Afterward the adapter tests run offline with that cache directory available. Without both grammars, all five tests skip by default. Set `VARDE_BENCH_REQUIRE_GRAMMARS=1` when running tests to make a missing grammar fail instead of skip.
