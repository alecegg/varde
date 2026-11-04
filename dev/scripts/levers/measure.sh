#!/usr/bin/env bash
set -euo pipefail

# Shared helpers for the Python lever measurements. Commands are measured one
# at a time so each gets its own idle gate, lock, and duration-matched baseline.
repo_root=$(git -C "$(dirname "${BASH_SOURCE[0]}")/../.." rev-parse --show-toplevel)
source_repo=/Users/alec/source/varde
tmp_root=${TMPDIR:-/tmp}/varde-py-levers
cache_root=${UV_CACHE_DIR:-${TMPDIR:-/tmp}/varde-py-uv-cache}
trials=${TRIALS:-5}
workers=$(sysctl -n hw.logicalcpu)
python_version=$(python3.14 --version 2>&1)
uv_version=$(uv --version)
mkdir -p "$tmp_root" "$cache_root"
export UV_CACHE_DIR=$cache_root UV_PYTHON_PREFERENCE=only-system

if [[ ! $trials =~ ^[5-9][0-9]*$|^[1-9][0-9]+$ ]]; then
  echo 'TRIALS must be at least 5' >&2; exit 2
fi

ioreg_bytes() {
  ioreg -c IOBlockStorageDriver -r -w0 | awk '/"Bytes \(Write\)"=/ {v=$0; sub(/^.*"Bytes \(Write\)"=/,"",v); sub(/[^0-9].*/,"",v); n+=v} END {print n+0}'
}

gate() {
  local deadline=$((SECONDS + ${GATE_TIMEOUT_SECONDS:-1800}))
  while ((SECONDS < deadline)); do
    local hits idle_file median
    hits=$(ps -axo pid=,comm=,args= | awk '{comm=$2; sub(".*/", "", comm); if (comm ~ /^(cargo|rustc|go|uv|pip|pyinstaller)$/ || (comm ~ /^python3([.]|$)/ && $0 ~ /(pyinstaller|uv[ -]pip)/)) print $0}')
    if [[ -d /Users/alec/source/.varde-measure.lock ]]; then hits="${hits}${hits:+$'\n'}shared measurement lock held"; fi
    idle_file=$(mktemp "${TMPDIR:-/tmp}/varde-idle.XXXXXX")
    for _ in 1 2 3 4 5; do
      local before after
      before=$(ioreg_bytes); sleep 2; after=$(ioreg_bytes)
      printf '%s\n' "$((after-before))" >> "$idle_file"
    done
    median=$(sort -n "$idle_file" | sed -n '3p')
    rm -f "$idle_file"
    if [[ -z $hits ]] && ((median < 1000000)); then return 0; fi
    printf 'idle gate failed; retrying in 10s (competing=%s, five-sample median=%s bytes)\n' "$(printf '%s\n' "$hits" | sed '/^$/d' | wc -l | tr -d ' ')" "$median" >&2
    sleep 10
  done
  echo 'idle gate timed out; no measurements were started' >&2
  return 1
}

sample() {
  local label=$1 bytecode=$2 link_mode=$3; shift 3
  printf 'ENV|python=%s|uv=%s|link_mode=%s|bytecode=%s|label=%s\n' "$python_version" "$uv_version" "$link_mode" "$bytecode" "$label"
  gate
  TRIALS=1 "$repo_root/dev/scripts/with-lock.sh" "$repo_root/dev/scripts/wear.sh" --locked "$label" "$@"
}

serialized() {
  gate
  "$repo_root/dev/scripts/with-lock.sh" "$@"
}

new_project() {
  local root=$1
  serialized git clone --quiet --local --no-hardlinks "$repo_root" "$root/project"
  serialized uv venv "$root/project/.venv" >/dev/null
}

install_project() {
  local project=$1 mode=$2
  serialized uv sync --project "$project" --locked --link-mode "$mode" >/dev/null
}

index_command() {
  local project=$1 db=$2 grammars=$3
  printf -v INDEX_COMMAND '%q ' uv run --project "$project" python -m varde_py index "$source_repo" --db "$db" --workers "$workers" --grammars "$grammars"
  read -r -a INDEX_ARGS <<<"$INDEX_COMMAND"
}

usage() {
  echo "usage: $0 {uv-links|shared-venv|bytecode|sqlite|pyinstaller-trim|zipapps|nuitka|combined} [21|18]" >&2
  exit 2
}

mode=${1:-}; count=${2:-21}
[[ $count == 21 || $count == 18 ]] || usage
if [[ $count == 21 ]]; then grammar_arg=21; else grammar_arg=rust,typescript,tsx,python,elixir,csharp,c,go,kotlin,swift,javascript,php,scala,lua,java,bash,cpp,ruby; fi
case $mode in
  uv-links)
    for link_mode in clone hardlink copy; do
      for trial in $(seq 1 "$trials"); do
        root=$(mktemp -d "$tmp_root/uv-$link_mode-$trial.XXXXXX")
        trap 'rm -rf "$root"' EXIT
        new_project "$root"; project=$root/project
        sample "uv-link-$link_mode-$trial" "sys.dont_write_bytecode=True" "$link_mode" uv sync --project "$project" --locked --link-mode "$link_mode"
        rm -rf "$root"; trap - EXIT
      done
    done
    ;;
  shared-venv)
    shared=$tmp_root/shared-venv
    [[ -x $shared/bin/python ]] || serialized uv venv "$shared" >/dev/null
    if [[ ! -f $shared/.varde-py-ready ]]; then
      serialized uv pip install --python "$shared/bin/python" --editable "$repo_root" >/dev/null
      touch "$shared/.varde-py-ready"
    fi
    for trial in $(seq 1 "$trials"); do
      root=$(mktemp -d "$tmp_root/shared-$trial.XXXXXX")
      trap 'rm -rf "$root"' EXIT
      serialized git clone --quiet --local --no-hardlinks "$repo_root" "$root/project"
      sample "shared-venv-editable-$trial" "sys.dont_write_bytecode=True" clone uv pip install --python "$shared/bin/python" --editable "$root/project"
      rm -rf "$root"; trap - EXIT
    done
    ;;
  bytecode|sqlite)
    for variant in $( [[ $mode == bytecode ]] && echo enabled || echo journal-off sync-off temp-memory pragmas memory-one-write ); do
      for trial in $(seq 1 "$trials"); do
        root=$(mktemp -d "$tmp_root/$mode-$variant-$trial.XXXXXX")
        trap 'rm -rf "$root"' EXIT
        new_project "$root"; project=$root/project
        install_project "$project" clone
        if [[ $mode == bytecode ]]; then
          python3.14 - "$project/src/varde_py/index.py" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); p.write_text(p.read_text().replace("sys.dont_write_bytecode = True", "sys.dont_write_bytecode = False"))
PY
          bytecode=sys.dont_write_bytecode=False
        else
          python3.14 - "$project/src/varde_py/index.py" "$variant" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); mode=sys.argv[2]; text=p.read_text()
old='    with sqlite3.connect(db_path) as db:\n        db.execute("DROP TABLE IF EXISTS entities")'
pragmas={
    "journal-off": '        db.execute("PRAGMA journal_mode=OFF")\n',
    "sync-off": '        db.execute("PRAGMA synchronous=OFF")\n',
    "temp-memory": '        db.execute("PRAGMA temp_store=MEMORY")\n',
    "pragmas": '        db.execute("PRAGMA journal_mode=OFF")\n        db.execute("PRAGMA synchronous=OFF")\n        db.execute("PRAGMA temp_store=MEMORY")\n',
}
if mode in pragmas:
    new='    with sqlite3.connect(db_path) as db:\n'+pragmas[mode]+'        db.execute("DROP TABLE IF EXISTS entities")'
else:
    old='    with sqlite3.connect(db_path) as db:\n        db.execute("DROP TABLE IF EXISTS entities")'
    new='    with sqlite3.connect(":memory:") as db:\n        db.execute("DROP TABLE IF EXISTS entities")'
    text=text.replace('    return count\n', '    if str(db_path) != ":memory:":\n        db_path.write_bytes(db.serialize())\n    return count\n')
if old not in text: raise SystemExit("expected SQLite write path not found")
p.write_text(text.replace(old,new))
PY
          bytecode=sys.dont_write_bytecode=True
        fi
        db=$root/index.sqlite; index_command "$project" "$db" "$grammar_arg"
        sample "$mode-$variant-index-$count-$trial" "$bytecode" clone "${INDEX_ARGS[@]}"
        rm -rf "$root"; trap - EXIT
      done
    done
    ;;
  pyinstaller-trim)
    for trial in $(seq 1 "$trials"); do
      root=$(mktemp -d "$tmp_root/$mode-$count-$trial.XXXXXX")
      trap 'rm -rf "$root"' EXIT
      new_project "$root"; project=$root/project
      install_project "$project" clone
      app=varde-py-trim-$count
      index_command "$project" "$root/index.sqlite" "$count"
      sample "$mode-build-$count-$trial" sys.dont_write_bytecode=True clone uv run --project "$project" pyinstaller --noconfirm --clean --workpath "$root/work" --distpath "$root/dist" --specpath "$root" --exclude-module pytest --exclude-module ruff --exclude-module pip --exclude-module setuptools --collect-submodules tree_sitter_language_pack.bindings --collect-binaries tree_sitter_language_pack --collect-data tree_sitter_language_pack --strip --noupx --onedir --name "$app" "$project/src/varde_py/index.py"
      sample "$mode-first-run-$count-$trial" sys.dont_write_bytecode=True clone "$root/dist/$app/$app" index "$source_repo" --db "$root/run.sqlite" --workers "$workers" --grammars "$grammar_arg"
      rm -rf "$root"; trap - EXIT
    done
    ;;
  combined)
    shared=$tmp_root/shared-venv
    [[ -x $shared/bin/python ]] || { echo 'shared venv is missing; run shared-venv first' >&2; exit 2; }
    for trial in $(seq 1 "$trials"); do
      root=$(mktemp -d "$tmp_root/combined-$count-$trial.XXXXXX")
      trap 'rm -rf "$root"' EXIT
      serialized git clone --quiet --local --no-hardlinks "$repo_root" "$root/project"
      sample "combined-pex-e2e-$count-$trial" sys.dont_write_bytecode=True clone bash -c '
        set -euo pipefail
        python=$1; project=$2; root=$3; source=$4; grammars=$5; workers=$6
        uv pip install --python "$python" --editable "$project" >/dev/null
        export PEX_ROOT="$root/pex-root"
        uv tool run --from pex pex "$project" -o "$root/app.pex" -e varde_py.index:main --python-shebang "$python"
        "$root/app.pex" index "$source" --db "$root/index.sqlite" --workers "$workers" --grammars "$grammars"
        printf "# measured edit\\n" >> "$project/src/varde_py/index.py"
        uv tool run --from pex pex "$project" -o "$root/app.pex" -e varde_py.index:main --python-shebang "$python"
        "$root/app.pex" index "$source" --db "$root/edit.sqlite" --workers "$workers" --grammars "$grammars"
      ' _ "$shared/bin/python" "$root/project" "$root" "$source_repo" "$grammar_arg" "$workers"
      rm -rf "$root"; trap - EXIT
    done
    ;;
  zipapps)
    for tool in zipapp shiv pex; do
      # Install the packager once into the shared cache/tool environment; only
      # the project packaging and launch are measured below.
      for trial in $(seq 1 "$trials"); do
        root=$(mktemp -d "$tmp_root/$tool-$count-$trial.XXXXXX")
        trap 'rm -rf "$root"' EXIT
        new_project "$root"; project=$root/project
        install_project "$project" clone
        mkdir -p "$root/stage/varde_py"
        cp "$project/src/varde_py/"*.py "$root/stage/varde_py/"
        printf 'from varde_py.index import main\nraise SystemExit(main())\n' > "$root/stage/__main__.py"
        case $tool in
          zipapp)
            sample "zipapp-build-$count-$trial" sys.dont_write_bytecode=True clone python3.14 -m zipapp "$root/stage" --python "$project/.venv/bin/python" --output "$root/app.pyz"
            executable="$root/app.pyz"
            ;;
          shiv)
            site=$project/.venv/lib/python3.14/site-packages
            sample "shiv-build-$count-$trial" sys.dont_write_bytecode=True clone uv tool run --from shiv shiv --site-packages "$site" --entry-point varde_py.index:main --output-file "$root/app.pyz"
            executable="$root/app.pyz"
            ;;
          pex)
            sample "pex-build-$count-$trial" sys.dont_write_bytecode=True clone uv tool run --from pex pex "$project" -o "$root/app.pex" -e varde_py.index:main --python-shebang "$project/.venv/bin/python"
            executable="$root/app.pex"
            ;;
        esac
        if [[ $tool == zipapp ]]; then
          sample "zipapp-first-run-$count-$trial" sys.dont_write_bytecode=True clone "$executable" index "$source_repo" --db "$root/run.sqlite" --workers "$workers" --grammars "$grammar_arg"
        else
          sample "$tool-first-run-$count-$trial" sys.dont_write_bytecode=True clone "$executable" index "$source_repo" --db "$root/run.sqlite" --workers "$workers" --grammars "$grammar_arg"
        fi
        rm -rf "$root"; trap - EXIT
      done
    done
    ;;
  nuitka)
    root=$(mktemp -d "$tmp_root/nuitka-$count.XXXXXX")
    trap 'rm -rf "$root"' EXIT
    new_project "$root"; project=$root/project
    install_project "$project" clone
    sample "nuitka-one-attempt-$count" sys.dont_write_bytecode=True clone python3.14 -c 'import subprocess,sys; sys.exit(subprocess.run(["uv","run","--project",sys.argv[1],"--with","nuitka","python","-m","nuitka","--standalone","--output-dir="+sys.argv[2],"--include-package=tree_sitter_language_pack",sys.argv[1]+"/src/varde_py/index.py"],timeout=1800).returncode)' "$project" "$root/nuitka-out"
    rm -rf "$root"; trap - EXIT
    ;;
  *) usage ;;
esac
