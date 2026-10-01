#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTAKE="$SCRIPT_DIR/../varde-review/scripts/pr-intake.py"
PY="$(command -v python3)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/pr-intake.XXXXXX")"
trap 'chmod -R u+w "$TEST_ROOT"; rm -rf "$TEST_ROOT"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

FX="$TEST_ROOT/fx"; BIN="$TEST_ROOT/bin"; REPO="$TEST_ROOT/repo"
mkdir -p "$FX" "$BIN" "$REPO"
git -C "$REPO" init -q
git -C "$REPO" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
HEAD_OID="$(git -C "$REPO" rev-parse HEAD)"

# Fake gh: serves fixtures from $FX and logs "<GH_HOST> <args>" to $FX/calls.log.
cat > "$BIN/gh" <<'GH'
#!/usr/bin/env bash
echo "${GH_HOST:-} $1 $2 $3 $4" >> "$FX/calls.log"
case "$1 $2" in
  "auth status") exit "$(cat "$FX/auth.rc" 2>/dev/null || echo 0)" ;;
  "repo view") cat "$FX/repo.json"; exit "$(cat "$FX/repo.rc" 2>/dev/null || echo 0)" ;;
  "pr view") cat "$FX/pr.json" ;;
  "pr checks")
    cat "$FX/checks.out" 2>/dev/null || true
    cat "$FX/checks.err" >&2 2>/dev/null || true
    exit "$(cat "$FX/checks.rc" 2>/dev/null || echo 0)" ;;
  "api graphql")
    id=""; cursor="first"
    for a in "$@"; do
      case "$a" in id=*) id="${a#id=}" ;; endCursor=*) cursor="${a#endCursor=}" ;; esac
    done
    if [ -n "$id" ]; then cat "$FX/node-$id-$cursor.json"; else cat "$FX/threads.json"; fi ;;
  *) echo "unexpected gh $*" >&2; exit 9 ;;
esac
GH
chmod +x "$BIN/gh"

reset() {
  rm -f "$FX"/*
  cat > "$FX/pr.json" <<JSON
{"number":7,"url":"https://github.example.com/acme/widgets/pull/7","state":"OPEN",
 "headRefName":"feat","headRefOid":"$HEAD_OID",
 "comments":[{"author":{"login":"carol"},"body":"conv","url":"u-conv"}]}
JSON
  echo '{"url":"https://github.example.com/acme/widgets"}' > "$FX/repo.json"
  echo '[]' > "$FX/checks.out"
  # Page 1: T1 unresolved, T2 resolved. Page 2: T3 outdated unresolved, T4 with >100 comments.
  cat > "$FX/threads.json" <<'JSON'
[
 {"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"id":"T1","isResolved":false,"isOutdated":false,"path":"a.rs","line":3,"originalLine":3,
   "comments":{"nodes":[{"body":"b1","url":"u1","author":{"login":"alice"}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}},
  {"id":"T2","isResolved":true,"isOutdated":false,"path":"b.rs","line":1,"originalLine":1,
   "comments":{"nodes":[{"body":"b2","url":"u2","author":{"login":"bob"}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}
 ],"pageInfo":{"hasNextPage":true,"endCursor":"p1"}}}}}},
 {"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[
  {"id":"T3","isResolved":false,"isOutdated":true,"path":"c.rs","line":null,"originalLine":9,
   "comments":{"nodes":[{"body":"b3","url":"u3","author":null}],"pageInfo":{"hasNextPage":false,"endCursor":null}}},
  {"id":"T4","isResolved":false,"isOutdated":false,"path":"d.rs","line":4,"originalLine":4,
   "comments":{"nodes":[{"body":"b4a","url":"u4a","author":{"login":"alice"}}],"pageInfo":{"hasNextPage":true,"endCursor":"c1"}}}
 ],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}}
]
JSON
  echo '{"data":{"node":{"comments":{"nodes":[{"body":"b4b","url":"u4b","author":{"login":"bob"}}],"pageInfo":{"hasNextPage":true,"endCursor":"c2"}}}}}' > "$FX/node-T4-c1.json"
  echo '{"data":{"node":{"comments":{"nodes":[{"body":"b4c","url":"u4c","author":{"login":"alice"}}],"pageInfo":{"hasNextPage":false,"endCursor":null}}}}}' > "$FX/node-T4-c2.json"
}

run() { # run <pr> -> sets OUT and RC
  set +e
  OUT="$(cd "$REPO" && FX="$FX" PATH="$BIN:$PATH" "$PY" "$INTAKE" "$@" 2>"$TEST_ROOT/stderr")"
  RC=$?
  set -e
}
check() { # check <label> <python expression over d>
  printf '%s' "$OUT" | "$PY" -c "import json,sys; d=json.load(sys.stdin); assert $2, d" \
    || fail "$1: $OUT"
}
expect_rc() { [ "$RC" -eq "$2" ] || fail "$1: exit $RC (want $2): $OUT"; }

# threads: pages merged, resolved dropped, outdated kept, >100-comment thread paged
reset; run https://github.example.com/acme/widgets/pull/7
expect_rc "happy path" 0 0
check "thread ids" "[t['id'] for t in d['threads']] == ['T1','T3','T4']"
check "outdated kept" "d['threads'][1]['is_outdated'] and d['threads'][1]['original_line'] == 9"
check "node paging" "[c['body'] for c in d['threads'][2]['comments']] == ['b4a','b4b','b4c']"
check "pr fields" "d['pr']['owner']=='acme' and d['pr']['repo']=='widgets' and d['pr']['head_oid']=='$HEAD_OID' and d['pr']['host']=='github.example.com'"
check "conversation" "d['conversation_comments'] == [{'author':'carol','body':'conv','url':'u-conv'}]"
check "empty checks" "d['failing_checks'] == []"
check "null author" "d['threads'][1]['comments'][0]['author'] is None"

# host from URL: every gh call carries it, and repo view is not needed
grep -q '^github.example.com ' "$FX/calls.log" || fail "GH_HOST not set from URL"
! grep -q '^ ' "$FX/calls.log" || fail "a gh call ran without GH_HOST"
! grep -q 'repo view' "$FX/calls.log" || fail "repo view used despite URL"

# host from repo view when <pr> is a number
reset; echo '{"url":"https://ghe.corp.test/acme/widgets"}' > "$FX/repo.json"; run 7
expect_rc "repo view host" 0 0
grep -q '^ghe.corp.test auth status -h ghe.corp.test' "$FX/calls.log" || fail "host from repo view not used"
[ "$(grep -c '^ ' "$FX/calls.log")" -eq 1 ] || fail "only repo view may run without GH_HOST"
grep -q '^  *repo view' "$FX/calls.log" || fail "the call without GH_HOST was not repo view"

# checks: exit 1 and exit 8 with a valid array keep only bucket fail
CHECKS='[{"name":"build","state":"FAILURE","bucket":"fail","link":"l1","description":"d","workflow":"ci"},{"name":"lint","state":"SUCCESS","bucket":"pass","link":"l2","description":"","workflow":"ci"},{"name":"slow","state":"PENDING","bucket":"pending","link":"l3","description":"","workflow":"ci"}]'
for rc in 1 8; do
  reset; echo "$CHECKS" > "$FX/checks.out"; echo "$rc" > "$FX/checks.rc"; run 7
  expect_rc "checks exit $rc" 0 0
  check "checks exit $rc" "[c['name'] for c in d['failing_checks']] == ['build']"
done

# no checks: gh 2.101.0 prints this on stderr, exits 1, writes nothing to stdout
reset; : > "$FX/checks.out"; echo 1 > "$FX/checks.rc"
echo "no checks reported on the 'feat' branch" > "$FX/checks.err"; run 7
expect_rc "no checks (gh error)" 0 0
check "no checks (gh error)" "d['failing_checks'] == []"
# exit 0 with an empty array also means no failing checks (covered by the happy path)

# narrow match: auth, API, and look-alike errors are not "no checks"
for err in "HTTP 401: Bad credentials" "error connecting to api.github.com" "no checks reported on the 'feat' branch; try again" "no required checks reported on the 'feat' branch"; do
  reset; : > "$FX/checks.out"; echo 1 > "$FX/checks.rc"; echo "$err" > "$FX/checks.err"; run 7
  expect_rc "not no-checks: $err" 3
done

# non-JSON stdout with nonzero exit, and a nonzero exit outside 1/8
reset; echo "boom" > "$FX/checks.out"; echo 1 > "$FX/checks.rc"; run 7
expect_rc "non-JSON stdout" 3
reset; echo "$CHECKS" > "$FX/checks.out"; echo 4 > "$FX/checks.rc"; run 7
expect_rc "exit 4 with array" 3

# typed preflight exits
reset; echo 1 > "$FX/auth.rc"; run 7
expect_rc "auth" 2; check "auth" "d['error'] == 'auth'"
reset; sed -i.bak 's/"OPEN"/"MERGED"/' "$FX/pr.json"; run 7
expect_rc "not_open" 2; check "not_open" "d['error'] == 'not_open'"
reset; sed -i.bak "s/$HEAD_OID/0000000000000000000000000000000000000000/" "$FX/pr.json"; run 7
expect_rc "head_mismatch" 2; check "head_mismatch" "d['error'] == 'head_mismatch'"
reset
set +e
OUT="$(cd "$REPO" && FX="$FX" PATH=/nonexistent "$PY" "$INTAKE" 7)"; RC=$?
set -e
expect_rc "gh_missing" 2; check "gh_missing" "d['error'] == 'gh_missing'"

# repo view failure: auth failure is typed auth (2), otherwise api (3)
reset; echo 1 > "$FX/repo.rc"; echo 1 > "$FX/auth.rc"; run 7
expect_rc "repo view + auth failure" 2; check "repo view + auth failure" "d['error'] == 'auth'"
reset; echo 1 > "$FX/repo.rc"; run 7
expect_rc "repo view failure, auth ok" 3; check "repo view failure, auth ok" "d['error'] == 'api'"

# malformed shapes are typed api errors, not tracebacks
reset; sed -i.bak 's/"pageInfo":{"hasNextPage":false,"endCursor":null}}},/}},/' "$FX/threads.json"; run 7
expect_rc "thread without pageInfo" 3; check "thread without pageInfo" "d['error'] == 'api'"
reset; sed -i.bak 's/"comments":{"nodes":\[{"body":"b1"/"nocomments":{"nodes":[{"body":"b1"/' "$FX/threads.json"; run 7
expect_rc "thread without comments" 3; check "thread without comments" "d['error'] == 'api'"
reset; sed -i.bak 's#"url":"https://github.example.com/acme/widgets/pull/7",##' "$FX/pr.json"; run 7
expect_rc "pr without url" 3; check "pr without url" "d['error'] == 'api'"

mutate() { # mutate <python statement over pages> rewrites the threads fixture
  "$PY" -c "import json,sys; pages=json.load(open(sys.argv[1])); $1; json.dump(pages, open(sys.argv[1],'w'))" "$FX/threads.json"
}
NODES='pages[0]["data"]["repository"]["pullRequest"]["reviewThreads"]'
reset; mutate "del $NODES['nodes'][0]['id']"; run 7
expect_rc "thread without id" 3; check "thread without id" "d['error'] == 'api' and 'no id' in d['message']"
reset; mutate "$NODES['nodes'][0]['id'] = None"; run 7
expect_rc "thread with null id" 3; check "thread with null id" "d['error'] == 'api' and 'no id' in d['message']"
reset; mutate "$NODES['nodes'] = {'x': 1}"; run 7
expect_rc "nodes not a list" 3; check "nodes not a list" "d['error'] == 'api' and 'list of objects' in d['message']"
reset; mutate "$NODES['nodes'][0] = 'T1'"; run 7
expect_rc "non-object thread element" 3; check "non-object thread element" "d['error'] == 'api' and 'list of objects' in d['message']"

# usage
run; expect_rc "usage" 1

echo "pr-intake: all checks passed"
