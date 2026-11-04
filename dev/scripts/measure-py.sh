#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
measure_root=${TMPDIR:-/tmp}/varde-py-measure
cache_root=${UV_CACHE_DIR:-${TMPDIR:-/tmp}/varde-py-uv-cache}
source_repo=/Users/alec/source/varde
python_preference=only-system
export UV_PYTHON_PREFERENCE=$python_preference UV_CACHE_DIR=$cache_root
export TRIALS=1
workers=$(sysctl -n hw.logicalcpu)
mkdir -p "$measure_root" "$cache_root"
mkdir -p "$measure_root/bin"
cat > "$measure_root/bin/sleep" <<'SLEEP_SHIM'
#!/usr/bin/env bash
set -euo pipefail
seconds=${1%%.*}
if [[ ! $seconds =~ ^[0-9]+$ ]]; then seconds=0; fi
if [[ $1 == *.* ]]; then seconds=$((seconds + 1)); fi
if ((seconds < 1)); then seconds=1; fi
exec /bin/sleep "$seconds"
SLEEP_SHIM
chmod +x "$measure_root/bin/sleep"
export PATH="$measure_root/bin:$PATH"

if (($#)); then
  echo "usage: dev/scripts/measure-py.sh" >&2
  exit 2
fi

worktree=$(mktemp -d "$measure_root/run.XXXXXX")
cleanup() { rm -rf "$worktree"; }
trap cleanup EXIT

# Use an independent temporary clone: the protected source checkout is never read by Python.
git clone --quiet --local --no-hardlinks "$source_repo" "$worktree/corpus"

run_wear() {
  local label=$1; shift
  local time_file="$measure_root/$label.time"
  local status=0
  "$repo_root/dev/scripts/wear.sh" "$label" /usr/bin/time -p "$@" 2>"$time_file" || status=$?
  cat "$time_file" >&2
  local wall_seconds
  wall_seconds=$(awk '$1 == "real" {print $2; exit}' "$time_file")
  printf 'WALL|%s|real_seconds=%s\n' "$label" "${wall_seconds:-unavailable}"
  return "$status"
}
run_variant_wear() {
  local label=$1; shift
  if [[ $variant == venv-no-bytecode ]]; then
    run_wear "$label" env PYTHONDONTWRITEBYTECODE=1 "$@"
  else
    run_wear "$label" env -u PYTHONDONTWRITEBYTECODE "$@"
  fi
}

python_version=$(python3.14 --version 2>&1)
link_mode=clone
bytecode=off

# Warm the shared wheel cache before trial measurements.
"$repo_root/dev/scripts/with-lock.sh" uv sync --project "$repo_root" --locked --link-mode "$link_mode"

for variant in venv venv-no-bytecode pyinstaller-onedir; do
  for trial in 1 2 3; do
    trial_root="$worktree/$variant-$trial"
    mkdir -p "$trial_root"
    cp -R "$repo_root/src" "$repo_root/tests" "$trial_root/"
    cp "$repo_root/pyproject.toml" "$repo_root/uv.lock" "$repo_root/.python-version" "$trial_root/"
    mkdir -p "$trial_root/docs"
    cp "$repo_root/README.md" "$trial_root/"
    perl -0pi -e 's/from __future__ import annotations\n\nimport sys\n\nsys\.dont_write_bytecode = True\n\n/from __future__ import annotations\n\n/' "$trial_root/src/varde_py/index.py"
    bytecode=on
    bytecode_env=()
    if [[ $variant == venv-no-bytecode ]]; then bytecode=off; bytecode_env=(PYTHONDONTWRITEBYTECODE=1); fi

    run_wear "$variant-setup-$trial" uv sync --project "$trial_root" --locked --link-mode "$link_mode"
    db="$worktree/$variant-$trial.sqlite"
    if [[ $variant == pyinstaller-onedir ]]; then
      run_wear "$variant-package-$trial" uv run --project "$trial_root" --directory "$trial_root" pyinstaller --noconfirm --clean --collect-all tree_sitter_language_pack --onedir --name varde-py "$trial_root/src/varde_py/index.py"
      executable="$trial_root/dist/varde-py/varde-py"
      run_wear "$variant-first-index-$trial" "$executable" index "$worktree/corpus" --db "$db" --workers "$workers" --grammars 4
      run_wear "pyinstaller-onefile-package-$trial" uv run --project "$trial_root" --directory "$trial_root" pyinstaller --noconfirm --clean --collect-all tree_sitter_language_pack --onefile --name varde-py-onefile "$trial_root/src/varde_py/index.py"
      onefile="$trial_root/dist/varde-py-onefile"
      run_wear "pyinstaller-onefile-first-index-$trial" "$onefile" index "$worktree/corpus" --db "$db" --workers "$workers" --grammars 4
      printf '# measure edit\n' >> "$trial_root/src/varde_py/index.py"
      run_wear "$variant-edit-package-$trial" uv run --project "$trial_root" --directory "$trial_root" pyinstaller --noconfirm --clean --collect-all tree_sitter_language_pack --onedir --name varde-py "$trial_root/src/varde_py/index.py"
      executable="$trial_root/dist/varde-py/varde-py"
      run_wear "$variant-edit-index-$trial" "$executable" index "$worktree/corpus" --db "$db" --workers "$workers" --grammars 4
      run_wear "pyinstaller-onefile-edit-package-$trial" uv run --project "$trial_root" --directory "$trial_root" pyinstaller --noconfirm --clean --collect-all tree_sitter_language_pack --onefile --name varde-py-onefile "$trial_root/src/varde_py/index.py"
      run_wear "pyinstaller-onefile-edit-index-$trial" "$onefile" index "$worktree/corpus" --db "$db" --workers "$workers" --grammars 4
    else
    run_variant_wear "$variant-first-index-$trial" uv run --project "$trial_root" python -m varde_py index "$worktree/corpus" --db "$db" --workers "$workers" --grammars 4
      printf '# measure edit\n' >> "$trial_root/src/varde_py/index.py"
      run_variant_wear "$variant-edit-index-$trial" uv run --project "$trial_root" python -m varde_py index "$worktree/corpus" --db "$db" --workers "$workers" --grammars 4
    fi
    run_variant_wear "$variant-ast-default-$trial" uv run --project "$trial_root" python -c 'import ast,pathlib; ast.parse(pathlib.Path("src/varde_py/index.py").read_text())'
    run_variant_wear "$variant-ruff-default-$trial" uv run --project "$trial_root" --directory "$trial_root" ruff check --config "$trial_root/pyproject.toml" --select E4,E7,E9,F src tests
    run_variant_wear "$variant-pytest-default-$trial" uv run --project "$trial_root" pytest
    run_wear "$variant-ast-no-cache-$trial" env PYTHONDONTWRITEBYTECODE=1 RUFF_CACHE_DIR="$worktree/ruff-cache" MYPY_CACHE_DIR="$worktree/mypy-cache" uv run --project "$trial_root" python -c 'import ast,pathlib; ast.parse(pathlib.Path("src/varde_py/index.py").read_text())'
    run_wear "$variant-ruff-no-cache-$trial" env PYTHONDONTWRITEBYTECODE=1 RUFF_CACHE_DIR="$worktree/ruff-cache" MYPY_CACHE_DIR="$worktree/mypy-cache" uv run --project "$trial_root" --directory "$trial_root" ruff check --config "$trial_root/pyproject.toml" --select E4,E7,E9,F src tests
    run_wear "$variant-pytest-no-cache-$trial" env PYTHONDONTWRITEBYTECODE=1 RUFF_CACHE_DIR="$worktree/ruff-cache" MYPY_CACHE_DIR="$worktree/mypy-cache" uv run --project "$trial_root" pytest -p no:cacheprovider
    if [[ $variant == pyinstaller-onedir ]]; then
      du -sk "$trial_root/dist/varde-py" | awk -v variant="$variant" -v trial="$trial" '{print "SIZE|variant=" variant "|trial=" trial "|kib=" $1}'
      du -sk "$trial_root/dist/varde-py-onefile" | awk -v variant="$variant-onefile" -v trial="$trial" '{print "SIZE|variant=" variant "|trial=" trial "|kib=" $1}'
    else
      du -sk "$trial_root/.venv" | awk -v variant="$variant" -v trial="$trial" '{print "SIZE|variant=" variant "|trial=" trial "|kib=" $1}'
    fi
    rm -f "$db"
  done
done

# Scale each grammar count in a fresh temporary project copy. Shared uv cache is warmed above.
for grammar_count in 4 8 12 21; do
  for trial in 1 2 3; do
    scale_root="$worktree/scale-$grammar_count-$trial"
    mkdir -p "$scale_root"
    cp -R "$repo_root/src" "$scale_root/"
    cp "$repo_root/pyproject.toml" "$repo_root/uv.lock" "$repo_root/.python-version" "$scale_root/"
    cp "$repo_root/README.md" "$scale_root/"
    perl -0pi -e 's/from __future__ import annotations\n\nimport sys\n\nsys\.dont_write_bytecode = True\n\n/from __future__ import annotations\n\n/' "$scale_root/src/varde_py/index.py"
    run_wear "scale-$grammar_count-setup-$trial" uv sync --project "$scale_root" --locked --link-mode "$link_mode"
    run_wear "scale-$grammar_count-index-$trial" uv run --project "$scale_root" python -m varde_py index "$worktree/corpus" --db "$worktree/scale.sqlite" --workers "$workers" --grammars "$grammar_count"
    run_wear "scale-$grammar_count-import-$trial" uv run --project "$scale_root" python -c 'import time; started=time.perf_counter(); import tree_sitter_language_pack; print(f"import_ms={(time.perf_counter()-started)*1000:.3f}")'
    du -sk "$scale_root/.venv" | awk -v count="$grammar_count" -v trial="$trial" '{print "SIZE|grammars=" count "|trial=" trial "|kib=" $1}'
  done
done

printf 'ENV|python=%s|uv=%s|link_mode=%s|bytecode=%s|workers=%s|cache=%s|db=%s\n' \
  "$python_version" "$(uv --version)" "$link_mode" "$bytecode" "$workers" "$cache_root" "$worktree"
