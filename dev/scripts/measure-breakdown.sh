#!/usr/bin/env bash
set -euo pipefail

# Repeatable Python write breakdown. All worktrees and the shared uv cache live
# outside the source checkout. Each wear sample owns the shared measurement lock.
repo_root=$(git rev-parse --show-toplevel)
tmp_root=${TMPDIR:-/tmp}/varde-py-breakdown
cache_root=${UV_CACHE_DIR:-${TMPDIR:-/tmp}/varde-py-uv-cache}
source_repo=/Users/alec/source/varde
trials=${TRIALS:-5}
workers=$(sysctl -n hw.logicalcpu)
link_mode=${UV_LINK_MODE:-clone}
mkdir -p "$tmp_root" "$cache_root"
export UV_CACHE_DIR=$cache_root UV_PYTHON_PREFERENCE=only-system

if [[ ! $trials =~ ^[5-9][0-9]*$|^[1-9][0-9]+$ ]]; then
  echo 'TRIALS must be at least 5' >&2; exit 2
fi
if (($#)); then echo "usage: $0" >&2; exit 2; fi

ioreg_bytes() {
  ioreg -c IOBlockStorageDriver -r -w0 | awk '/"Bytes \(Write\)"=/ {v=$0; sub(/^.*"Bytes \(Write\)"=/,"",v); sub(/[^0-9].*/,"",v); n+=v} END {print n+0}'
}
gate() {
  local deadline=$((SECONDS + ${GATE_TIMEOUT_SECONDS:-1800}))
  while ((SECONDS < deadline)); do
    local hits idle_file median
    hits=$(ps -axo pid=,comm=,args= | awk '{comm=$2; sub(".*/", "", comm); if (comm ~ /^(cargo|rustc|go|uv|pip|pyinstaller)$/ || (comm ~ /^python3([.]|$)/ && $0 ~ /(pyinstaller|uv[ -]pip)/)) print $0}')
    if [[ -d /Users/alec/source/.varde-measure.lock ]]; then hits="${hits}${hits:+$'\n'}shared measurement lock held"; fi
    if [[ -e /Users/alec/source/agent-memory/projects/varde/working/metrics/probe/session.lock ]]; then hits="${hits}${hits:+$'\n'}probe session lock held"; fi
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
  local label=$1 project=$2 db=$3 phase=$4; shift 4
  gate
  local before after rc=0
  before=$(mktemp "${TMPDIR:-/tmp}/varde-files-before.XXXXXX")
  after=$(mktemp "${TMPDIR:-/tmp}/varde-files-after.XXXXXX")
  snapshot "$project" "$cache_root" "$db" > "$before"
  TRIALS=1 "$repo_root/dev/scripts/with-lock.sh" "$repo_root/dev/scripts/wear.sh" --locked "$label" "$@" || rc=$?
  snapshot "$project" "$cache_root" "$db" > "$after"
  python3.14 - "$before" "$after" "$label" "$phase" <<'PY'
from pathlib import Path
import sys
before, after = (Path(name) for name in sys.argv[1:3])
old = {line.rsplit("\t", 1)[-1] for line in before.read_text().splitlines()}
totals = {}
for line in after.read_text().splitlines():
    bucket, size, path = line.split("\t", 2)
    if path not in old:
        totals[bucket] = totals.get(bucket, 0) + int(size)
for bucket, size in sorted(totals.items()):
    print(f"FILES|{sys.argv[3]}|phase={sys.argv[4]}|directory={bucket}|created_bytes={size}|explanatory_not_wear=true")
PY
  rm -f "$before" "$after"
  return "$rc"
}
snapshot() {
  python3.14 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import sys
project, cache, db = map(Path, sys.argv[1:])
targets = {".venv": project / ".venv", "build/": project / "build", "dist/": project / "dist",
           "uv cache": cache, "db": db, "__pycache__": project}
work = project / "pyinstaller-work"
targets["PyInstaller work dir"] = work
seen = set()
for bucket, root in targets.items():
    if not root.exists():
        continue
    files = [root] if root.is_file() else root.rglob("*")
    for path in files:
        if not path.is_file() or (bucket == "__pycache__" and "__pycache__" not in path.parts):
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        print(f"{bucket}\t{path.stat().st_size}\t{key}")
PY
}

python_version=$(python3.14 --version 2>&1)
uv_version=$(uv --version)
printf 'ENV|python=%s|uv=%s|link_mode=%s|bytecode=script-default-sys-dont-write-bytecode|cache=%s\n' "$python_version" "$uv_version" "$link_mode" "$cache_root"

# A sample is a fresh isolated checkout; uv cache is intentionally shared.
for count in 21 18; do
  if ((count == 21)); then grammars=21; else grammars=rust,typescript,tsx,python,elixir,csharp,c,go,kotlin,swift,javascript,php,scala,lua,java,bash,cpp,ruby; fi
  for variant in venv onedir onefile; do
    for trial in $(seq 1 "$trials"); do
      root=$(mktemp -d "$tmp_root/${count}-${variant}-${trial}.XXXXXX")
      cleanup() { rm -rf "$root"; }
      trap cleanup EXIT
      project=$root/project
      db=$root/index.sqlite
      printf 'ENV|grammar_count=%s|variant=%s|trial=%s|python=%s|uv=%s|link_mode=%s|bytecode=script-default-sys-dont-write-bytecode\n' "$count" "$variant" "$trial" "$python_version" "$uv_version" "$link_mode"
      sample "${count}-${variant}-checkout-${trial}" "$project" "$db" checkout git clone --quiet --local --no-hardlinks "$repo_root" "$project"
      sample "${count}-${variant}-venv-create-${trial}" "$project" "$db" venv-create uv venv "$project/.venv"
      sample "${count}-${variant}-locked-install-${trial}" "$project" "$db" locked-install uv sync --project "$project" --locked --link-mode "$link_mode"
      if [[ $variant == venv ]]; then
        run=(uv run --project "$project" python -m varde_py index "$source_repo" --db "$db" --workers "$workers" --grammars "$grammars")
        sample "${count}-${variant}-index-${trial}" "$project" "$db" index "${run[@]}"
        printf '# measured edit\n' >> "$project/src/varde_py/index.py"
        sample "${count}-${variant}-edit-rerun-${trial}" "$project" "$db" edit-rerun "${run[@]}"
      else
        mode=--onedir; app=varde-py
        if [[ $variant == onefile ]]; then mode=--onefile; app=varde-py-onefile; fi
        package=(uv run --project "$project" --directory "$project" pyinstaller --noconfirm --clean --workpath "$project/pyinstaller-work" --collect-all tree_sitter_language_pack "$mode" --name "$app" "$project/src/varde_py/index.py")
        sample "${count}-${variant}-package-build-${trial}" "$project" "$db" package-build "${package[@]}"
        executable=$project/dist/$app/$app
        if [[ $variant == onefile ]]; then executable=$project/dist/$app; fi
        sample "${count}-${variant}-first-run-${trial}" "$project" "$db" first-run "$executable" index "$source_repo" --db "$db" --workers "$workers" --grammars "$grammars"
        printf '# measured edit\n' >> "$project/src/varde_py/index.py"
        sample "${count}-${variant}-edit-package-build-${trial}" "$project" "$db" edit-package-build "${package[@]}"
        executable=$project/dist/$app/$app
        if [[ $variant == onefile ]]; then executable=$project/dist/$app; fi
        sample "${count}-${variant}-edit-rerun-${trial}" "$project" "$db" edit-rerun "$executable" index "$source_repo" --db "$db" --workers "$workers" --grammars "$grammars"
      fi
      rm -rf "$root"; trap - EXIT
    done
  done
done

echo 'Idle noise floor: each of at least five trials records a paired, equal-duration idle sample; retain every raw row.'
