#!/usr/bin/env bash
set -euo pipefail
script="$(cd "$(dirname "$0")/../varde-change/scripts" && pwd)/measure-writes.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export VARDE_WRITE_LEDGER="$tmp/metrics/build-writes.jsonl"
root="$tmp/output"
mkdir -p "$root"
git -C "$root" init -q
git -C "$root" config user.name test
git -C "$root" config user.email test@example.invalid
echo baseline > "$root/.baseline"
git -C "$root" add .baseline
git -C "$root" commit -qm baseline
rm "$root/.baseline"
sleep 1
failure_root="$tmp/failure-output"
mkdir -p "$failure_root"

set +e
(cd "$root" && bash "$script" run --root "$root" --label fixture -- bash -c 'head -c 5000 /dev/zero > "$1/a"; head -c 5000 /dev/zero > "$1/b"; exit 7' _ "$root")
status=$?
set -e
[[ "$status" == 7 ]]
[[ "$(tail -n 1 "$VARDE_WRITE_LEDGER" | jq -r .bytes)" == 10000 ]]
[[ "$(tail -n 1 "$VARDE_WRITE_LEDGER" | jq -r .files)" == 2 ]]
repo_root="$root"
[[ "$(tail -n 1 "$VARDE_WRITE_LEDGER" | jq -r .worktree)" == "$(basename "$repo_root")" ]]
[[ "$(tail -n 1 "$VARDE_WRITE_LEDGER" | jq -r .repo)" == "$repo_root" ]]
[[ "$(wc -l < "$VARDE_WRITE_LEDGER" | tr -d ' ')" == 1 ]]

# An unavailable working-directory lookup must not prevent the command or
# replace its exit status.
mkdir -p "$tmp/no-varde"
cat > "$tmp/no-varde/varde" <<'STUB'
#!/usr/bin/env bash
echo 'setup paths unavailable' >&2
exit 1
STUB
chmod +x "$tmp/no-varde/varde"
set +e
output="$(PATH="$tmp/no-varde:$PATH" VARDE_WRITE_LEDGER= bash "$script" run --root "$failure_root" -- bash -c 'echo ran > "$1/lookup-ran"; exit 7' _ "$failure_root" 2>&1)"
status=$?
set -e
[[ "$status" == 7 && -f "$failure_root/lookup-ran" ]]
grep -q 'warning:.*working directory' <<<"$output"

# A bad ledger destination has the same best-effort behavior.
printf 'file\n' > "$tmp/not-a-directory"
set +e
output="$(VARDE_WRITE_LEDGER="$tmp/not-a-directory/ledger.jsonl" bash "$script" run --root "$failure_root" -- bash -c 'echo ran > "$1/ledger-ran"; exit 9' _ "$failure_root" 2>&1)"
status=$?
set -e
[[ "$status" == 9 && -f "$failure_root/ledger-ran" ]]
grep -q 'warning:.*ledger' <<<"$output"

# Backdate the git metadata so a day sweep counts only the fixture's own writes.
find "$root/.git" -exec touch -t 199912301200 {} +
today="$(date +%F)"
empty_day="2000-01-01"
bash "$script" sweep --root "$root" --day "$today" >/dev/null
[[ "$(bash "$script" sweep --root "$root" --day "$today" | sed -n 's/.*bytes=\([0-9]*\).*/\1/p')" == 10000 ]]
[[ "$(awk -F '\t' -v d="$today" '$1==d {n++} END {print n+0}' "$(dirname "$VARDE_WRITE_LEDGER")/sweep.tsv")" == 1 ]]
bash "$script" sweep --root "$root" --day "$empty_day" >/dev/null
[[ "$(awk -F '\t' -v d="$empty_day" '$1==d {print $2}' "$(dirname "$VARDE_WRITE_LEDGER")/sweep.tsv")" == 0 ]]
report="$(bash "$script" report --days 1 --budget-gb 0.000001)"
grep -q OVER <<<"$report"
[[ "$(bash "$script" report --days 7)" == *"Verdict:"* ]]

sample="$tmp/sample-ledger.jsonl"
if [[ "$(uname -s)" == Darwin ]]; then
  VARDE_WRITE_LEDGER="$sample" bash "$script" sample
  sample_file="$(dirname "$sample")/device-writes.tsv"
  [[ "$(wc -l < "$sample_file" | tr -d ' ')" == 1 ]]
  awk -F '\t' 'NF==2 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {ok=1} END {exit !ok}' "$sample_file"
else
  set +e
  output="$(VARDE_WRITE_LEDGER="$sample" bash "$script" sample 2>&1)"
  status=$?
  set -e
  [[ "$status" == 2 && "$output" == *unsupported* ]]
fi
printf 'measure-writes tests passed\n'
