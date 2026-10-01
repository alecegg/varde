#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
OLD="$HOME/.config/opencode/agent"
NEW="$HOME/.config/opencode/agents"
mkdir -p "$OLD" "$NEW"
managed() { printf 'legacy\n<!-- varde-managed-agent -->\n' > "$1"; }
managed "$OLD/plan.md"
managed "$OLD/review.md"
managed "$OLD/build.md"
"$ROOT/install.sh" -t opencode -m -a varde-planner -n > "$TMP/preview"
[ -f "$OLD/plan.md" ] && [ ! -e "$NEW/varde-planner.md" ]
grep -Fq "$NEW/varde-planner.md" "$TMP/preview"
grep -Fq "Would remove legacy managed $OLD/plan.md" "$TMP/preview"
"$ROOT/install.sh" -t opencode -m -a varde-planner >/dev/null
[ -f "$NEW/varde-planner.md" ] && [ ! -e "$OLD/plan.md" ]
[ -f "$OLD/review.md" ] && [ -f "$OLD/build.md" ]
printf 'personal\n' > "$NEW/varde-reviewer.md"
"$ROOT/install.sh" -t opencode -m -a varde-reviewer >/dev/null
[ -f "$OLD/review.md" ] && [ "$(cat "$NEW/varde-reviewer.md")" = personal ]
printf 'personal legacy\n' > "$OLD/explore.md"
"$ROOT/install.sh" -t opencode -f -a varde-explorer >/dev/null
[ "$(cat "$OLD/explore.md")" = 'personal legacy' ]
ln -s "$TMP/absent" "$OLD/executor.md"
"$ROOT/install.sh" -t opencode -m -a varde-executor >/dev/null
[ -L "$OLD/executor.md" ] && [ ! -e "$OLD/build.md" ]
rm "$OLD/executor.md"
managed "$TMP/owned-target"
ln -s "$TMP/owned-target" "$OLD/executor.md"
"$ROOT/install.sh" -t opencode -m -a varde-executor >/dev/null
[ -L "$OLD/executor.md" ] && [ -f "$TMP/owned-target" ]
managed "$OLD/plan.md"
"$ROOT/install.sh" -t opencode -m -a varde-planner -d "$TMP/custom" >/dev/null
[ -f "$OLD/plan.md" ]
mkdir -p "$TMP/bin"
REAL_MV="$(command -v mv)"
cat > "$TMP/bin/cp" <<WRAP
#!/usr/bin/env bash
exit 1
WRAP
chmod +x "$TMP/bin/cp"
if PATH="$TMP/bin:$PATH" "$ROOT/install.sh" -t opencode -m -a varde-planner >"$TMP/failure" 2>&1; then exit 1; fi
[ -f "$OLD/plan.md" ]
rm "$TMP/bin/cp"
cat > "$TMP/bin/mv" <<WRAP
#!/usr/bin/env bash
case "\$1" in */.varde-agent.*) exit 1 ;; esac
exec "$REAL_MV" "\$@"
WRAP
chmod +x "$TMP/bin/mv"
cp "$NEW/varde-planner.md" "$TMP/before"
if PATH="$TMP/bin:$PATH" "$ROOT/install.sh" -t opencode -m -a varde-planner >"$TMP/failure" 2>&1; then exit 1; fi
[ -f "$OLD/plan.md" ]
cmp "$NEW/varde-planner.md" "$TMP/before"
rm "$TMP/bin/mv"
mv "$OLD" "$TMP/legacy-external"
ln -s "$TMP/legacy-external" "$OLD"
"$ROOT/install.sh" -t opencode -m -a varde-planner -n > "$TMP/symlink-preview"
! grep -Fq "Would remove legacy managed" "$TMP/symlink-preview"
"$ROOT/install.sh" -t opencode -m -a varde-planner >/dev/null
[ -L "$OLD" ] && [ -f "$TMP/legacy-external/plan.md" ]
echo 'OpenCode install migration checks passed'
