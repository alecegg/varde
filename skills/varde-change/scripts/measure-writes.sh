#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  measure-writes.sh run [--root DIR]... [--label LABEL] -- COMMAND [ARGS...]
  measure-writes.sh sweep --root DIR... [--day YYYY-MM-DD]
  measure-writes.sh report [--days N] [--budget-gb 10] [--margin-gb 7]
  measure-writes.sh sample

  VARDE_WRITE_LEDGER overrides the default ledger path.
  run prints writes: bytes=<n> files=<n> label=<label>.
USAGE
}

die() { printf 'measure-writes: %s\n' "$*" >&2; exit 1; }

working_dir() {
  local paths
  paths="$(varde setup paths --json)" || die 'could not resolve working directory'
  jq -er '.data.working' <<<"$paths"
}

ledger_path() {
  if [[ -n "${VARDE_WRITE_LEDGER:-}" ]]; then
    printf '%s\n' "$VARDE_WRITE_LEDGER"
  else
    printf '%s/metrics/build-writes.jsonl\n' "$(working_dir)"
  fi
}

sum_since() {
  local marker="$1" cutoff="${2:-}" root byte_count file_count total=0 files=0 listing stats
  shift 2
  for root in "$@"; do
    [[ -d "$root" ]] || continue
    listing="$(mktemp)"
    stats="$(mktemp)"
    find "$root" -type f -print0 >"$listing" 2>/dev/null
    if [[ "$(uname -s)" == Darwin ]]; then
      xargs -0 stat -c '%Y %s' <"$listing" >"$stats" 2>/dev/null || true
      if ! awk '$1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {found=1} END {exit !found}' "$stats"; then
        xargs -0 stat -f '%m %z' <"$listing" >"$stats" 2>/dev/null || true
      fi
    elif ! xargs -0 stat -c '%Y %s' <"$listing" >"$stats" 2>/dev/null; then
      xargs -0 stat -f '%m %z' <"$listing" >"$stats" 2>/dev/null || true
    fi
    read -r byte_count file_count < <(awk -v marker="$marker" -v cutoff="${cutoff:-0}" \
      '$1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ && $1 >= marker && (cutoff == 0 || $1 < cutoff) {bytes += $2; count++} END {print bytes+0, count+0}' "$stats")
    total=$((total + byte_count))
    files=$((files + file_count))
    rm -f "$listing" "$stats"
  done
  printf '%s %s\n' "$total" "$files"
}

metrics_dir() { dirname "$(ledger_path)"; }

run_ledger_path() {
  local paths working
  if [[ -n "${VARDE_WRITE_LEDGER:-}" ]]; then
    printf '%s\n' "$VARDE_WRITE_LEDGER"
    return 0
  fi
  if ! paths="$(varde setup paths --json 2>/dev/null)"; then
    printf 'measure-writes: warning: could not resolve working directory; skipped ledger write\n' >&2
    return 1
  fi
  if ! working="$(jq -er '.data.working' <<<"$paths" 2>/dev/null)"; then
    printf 'measure-writes: warning: could not resolve working directory; skipped ledger write\n' >&2
    return 1
  fi
  printf '%s/metrics/build-writes.jsonl\n' "$working"
}

run_command() {
  local label='' root marker started ended wall repo worktree cmd status ledger result bytes files
  local -a roots=() command=()
  while (($#)); do
    case "$1" in
      --root) (($# >= 2)) || die '--root requires a directory'; roots+=("$2"); shift 2 ;;
      --label) (($# >= 2)) || die '--label requires a value'; label="$2"; shift 2 ;;
      --) shift; command=("$@"); break ;;
      *) die "unexpected run argument: $1" ;;
    esac
  done
  ((${#command[@]})) || die 'run requires a command after --'
  if ((${#roots[@]} == 0)); then
    repo="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    roots=("$repo")
  fi
  marker="$(date +%s)"
  started="$marker"
  cmd="$(printf '%q ' "${command[@]}")"
  set +e
  "${command[@]}"
  status=$?
  set -e
  ended="$(date +%s)"
  wall=$((ended - started))
  result="$(sum_since "$marker" '' "${roots[@]}")"
  read -r bytes files <<<"$result"
  if ! ledger="$(run_ledger_path)"; then
    printf 'writes: bytes=%s files=%s label=%s\n' "$bytes" "$files" "$label"
    return "$status"
  fi
  if ! mkdir -p "$(dirname "$ledger")" 2>/dev/null; then
    printf 'measure-writes: warning: could not create ledger directory; skipped ledger write\n' >&2
    printf 'writes: bytes=%s files=%s label=%s\n' "$bytes" "$files" "$label"
    return "$status"
  fi
  repo="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)")"
  worktree="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || true)")"
  if ! jq -cn --argjson ts "$started" --arg label "$label" --arg cmd "$cmd" \
    --arg root "$(printf '%s\n' "${roots[@]}")" --argjson bytes "$bytes" \
    --argjson files "$files" --argjson exit "$status" --argjson wall_s "$wall" \
    --arg repo "$repo" --arg worktree "$worktree" \
    '{ts:$ts,label:$label,cmd:$cmd,root:$root,bytes:$bytes,files:$files,exit:$exit,wall_s:$wall_s,repo:$repo,worktree:$worktree}' >>"$ledger" 2>/dev/null; then
    printf 'measure-writes: warning: could not write ledger; skipped ledger entry\n' >&2
    printf 'writes: bytes=%s files=%s label=%s\n' "$bytes" "$files" "$label"
    return "$status"
  fi
  printf 'writes: bytes=%s files=%s label=%s\n' "$bytes" "$files" "$label"
  return "$status"
}

day_epoch() {
  local day="$1" result
  result="$(date -j -f '%Y-%m-%d %H:%M:%S' "$day 00:00:00" +%s 2>/dev/null)" && { printf '%s\n' "$result"; return; }
  date -d "$day 00:00:00" +%s 2>/dev/null
}

sweep() {
  local day="$(date +%F)" arg root start next result bytes files db dir tmp
  local -a roots=()
  while (($#)); do
    case "$1" in
      --root) (($# >= 2)) || die '--root requires a directory'; roots+=("$2"); shift 2 ;;
      --day) (($# >= 2)) || die '--day requires a date'; day="$2"; shift 2 ;;
      *) die "unexpected sweep argument: $1" ;;
    esac
  done
  ((${#roots[@]})) || die 'sweep requires at least one --root'
  [[ "$day" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || die "invalid day: $day"
  start="$(day_epoch "$day")" || die "cannot parse day: $day"
  if [[ "$(uname -s)" == Darwin ]]; then
    next="$(date -j -v+1d -f '%Y-%m-%d %H:%M:%S' "$day 00:00:00" +%s)"
  else
    next="$(date -d "$day + 1 day" +%s)"
  fi
  result="$(sum_since "$start" "$next" "${roots[@]}")"
  read -r bytes files <<<"$result"
  dir="$(metrics_dir)"
  mkdir -p "$dir"
  db="$dir/sweep.tsv"
  tmp="$(mktemp "${db}.XXXXXX")"
  if [[ -f "$db" ]]; then awk -F '\t' -v d="$day" '$1 != d' "$db" >"$tmp"; fi
  printf '%s\t%s\t%s\n' "$day" "$bytes" "$files" >>"$tmp"
  mv "$tmp" "$db"
  printf 'day=%s bytes=%s files=%s\n' "$day" "$bytes" "$files"
}

report() {
  local days=7 budget=10 margin=7 today day start total=0 gb verdict median max ledger
  while (($#)); do
    case "$1" in
      --days) (($# >= 2)) || die '--days requires a value'; days="$2"; shift 2 ;;
      --budget-gb) (($# >= 2)) || die '--budget-gb requires a value'; budget="$2"; shift 2 ;;
      --margin-gb) (($# >= 2)) || die '--margin-gb requires a value'; margin="$2"; shift 2 ;;
      *) die "unexpected report argument: $1" ;;
    esac
  done
  [[ "$days" =~ ^[1-9][0-9]*$ ]] || die '--days must be a positive integer'
  today="$(date +%F)"
  local -a vals=()
  for ((i=days-1; i>=0; i--)); do
    if [[ "$(uname -s)" == Darwin ]]; then day="$(date -j -v-${i}d -f '%Y-%m-%d' "$today" +%F)"; else day="$(date -d "$today - $i day" +%F)"; fi
    total="$(awk -F '\t' -v d="$day" '$1==d {v=$2} END {print v+0}' "$(metrics_dir)/sweep.tsv" 2>/dev/null || printf 0)"
    gb="$(awk -v b="$total" 'BEGIN {printf "%.3f", b/1000000000}')"
    vals+=("$gb")
    if awk -v b="$total" -v budget="$budget" 'BEGIN {exit !(b>budget*1000000000)}'; then verdict=OVER; else verdict=PASS; fi
    printf '%s  %s GB  %s\n' "$day" "$gb" "$verdict"
  done
  printf 'Top labels (ledger bytes):\n'
  ledger="$(ledger_path)"
  if [[ -f "$ledger" ]]; then jq -rs 'group_by(.label) | map({label:.[0].label,bytes:(map(.bytes)|add)}) | sort_by(-.bytes)[:5][] | "\(.label)\t\(.bytes)"' "$ledger"; fi
  printf 'Undercount: modified-artifact bytes count each surviving file size once; repeated rewrites, deleted files, and outputs outside swept roots are missed.\n'
  if ((days == 7)); then
    median="$(printf '%s\n' "${vals[@]}" | sort -n | awk 'NR==4 {print}')"
    max="$(printf '%s\n' "${vals[@]}" | sort -n | tail -n 1)"
    if awk -v m="$median" -v x="$max" -v margin="$margin" -v budget="$budget" 'BEGIN {exit !(m<=margin && x<=budget)}'; then verdict=PASS
    elif awk -v m="$median" -v x="$max" -v budget="$budget" 'BEGIN {exit !(m<=budget && x<=budget*1.4)}'; then verdict=MARGINAL
    else verdict=FAIL; fi
    printf 'Median: %s GB\nMax: %s GB\nVerdict: %s\n' "$median" "$max" "$verdict"
  fi
}

sample() {
  local os ts value file ledger
  os="$(uname -s)"
  if [[ "$os" != Darwin ]]; then printf 'unsupported\n'; return 2; fi
  value="$(ioreg -rc IOBlockStorageDriver | awk '!found && index($0, "\"Bytes (Write)\"=") {sub(/^.*\"Bytes \(Write\)\"=/, ""); sub(/,.*/, ""); gsub(/[^0-9]/, ""); print; found=1}')"
  [[ "$value" =~ ^[0-9]+$ ]] || die 'could not read internal disk write counter'
  ts="$(date +%s)"
  ledger="$(ledger_path)"
  file="$(dirname "$ledger")/device-writes.tsv"
  mkdir -p "$(dirname "$file")"
  printf '%s\t%s\n' "$ts" "$value" >>"$file"
  printf 'sample: ts=%s bytes=%s (internal disk; context only)\n' "$ts" "$value"
}

case "${1:-}" in
  run) shift; run_command "$@" ;;
  sweep) shift; sweep "$@" ;;
  report) shift; report "$@" ;;
  sample) shift; (($# == 0)) || die 'sample takes no arguments'; sample ;;
  -h|--help|help|'') usage ;;
  *) usage >&2; die "unknown subcommand: $1" ;;
esac
