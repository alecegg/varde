#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$SKILLS_DIR/varde-agent-doc-authoring/scripts/run-output-evals.sh"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_json() {
  local file="$1" expression="$2" message="$3"
  if ! jq -e "$expression" "$file" >/dev/null; then
    jq . "$file" >&2 || true
    fail "$message"
  fi
}

skill_dir="$TEST_ROOT/fixture-skill"
mock_bin="$TEST_ROOT/bin"
mkdir -p "$skill_dir/evals" "$mock_bin"
printf '%s\n' '# Fixture skill' > "$skill_dir/SKILL.md"
printf '%s\n' '{"skill_name":"fixture","evals":[{"id":"one","prompt":"test","assertions":["first","second"]}]}' \
  > "$skill_dir/evals/evals.json"

cat > "$mock_bin/claude" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$2" == *"You are grading"* ]]; then
  if [[ "${MOCK_JUDGE_TIMEOUT:-0}" == 1 ]]; then
    sleep 2
  fi
  if [[ "${MOCK_VERIFY_MODE:-0}" == 1 ]]; then
    [[ "$2" != *"filesystem artifact exists"* ]]
    [[ "$2" == *"transcript assertion passes"* ]]
    printf '%s\n' '{"result":"{\"results\":[{\"assertion\":\"transcript assertion passes\",\"verdict\":\"PASS\",\"evidence\":\"fixture output\"}]}"}'
    exit 0
  fi
  printf '%s\n' '{"result":"{\"results\":[{\"assertion\":\"first\",\"verdict\":\"PASS\",\"evidence\":\"yes\"},{\"assertion\":\"second\",\"verdict\":\"FAIL\",\"evidence\":\"no\"}]}"}'
  exit 0
fi

if [[ "${MOCK_VERIFY_MODE:-0}" == 1 ]]; then
  [[ -f seeded.txt ]]
  [[ -f template-input.txt ]]
  [[ ! -f prior-run.txt ]]
  printf '%s\n' "$@" > "$MOCK_ARGS_FILE"
  printf '%s\n' current > prior-run.txt
  printf '%s\n' done > filesystem-artifact.txt
  printf '%s\n' '{"result":"fixture output","duration_ms":1000,"usage":{"input_tokens":10,"output_tokens":10}}'
  exit 0
fi

if [[ "${MOCK_AGENT_TIMEOUT:-0}" == 1 ]]; then
  if [[ -n "${MOCK_DESCENDANT_MARKER:-}" ]]; then
    perl -e '$SIG{TERM} = "IGNORE"; sleep 2; open my $fh, ">", $ARGV[0] or die $!; print {$fh} "survived\n"' \
      "$MOCK_DESCENDANT_MARKER" &
  fi
  sleep 2
  printf '%s\n' '{"result":"late output","duration_ms":2000,"usage":{"input_tokens":10,"output_tokens":10}}'
  exit 0
fi

if [[ "$2" == test && -e .skill-under-evaluation ]]; then
  exit 3
fi

case "$MOCK_TOKEN_MODE" in
  measured)
    printf '%s\n' '{"result":"fixture output","duration_ms":1000,"total_cost_usd":0.25,"usage":{"input_tokens":120,"output_tokens":80,"cache_creation_input_tokens":30,"cache_read_input_tokens":50}}'
    ;;
  zero)
    printf '%s\n' '{"result":"fixture output","duration_ms":1000,"usage":{"input_tokens":0,"output_tokens":0}}'
    ;;
  null)
    printf '%s\n' '{"result":"fixture output","duration_ms":1000,"usage":{"input_tokens":null,"output_tokens":null}}'
    ;;
  unavailable)
    printf '%s\n' '{"result":"fixture output","duration_ms":1000}'
    ;;
  *)
    exit 2
    ;;
esac
MOCK
chmod +x "$mock_bin/claude"

"$RUNNER" --help | grep -F 'missing dependency (jq / claude / perl)' \
  >/dev/null || fail "runner help omits a required dependency"

run_fixture() {
  local mode="$1" workspace="$TEST_ROOT/$1-workspace"
  PATH="$mock_bin:$PATH" MOCK_TOKEN_MODE="$mode" \
    "$RUNNER" "$skill_dir" --workspace "$workspace" >/dev/null 2>&1
  printf '%s\n' "$workspace/iteration-1/benchmark.json"
}

measured="$(run_fixture measured)"
assert_json "$measured" '.run_summary.with_skill.pass_rate.mean == 0.5' \
  "measured fixture changed pass-rate reporting"
assert_json "$measured" '.run_summary.with_skill.tokens.mean == 280' \
  "measured fixture changed token reporting"
assert_json "$measured" '.run_summary.with_skill.time_seconds.mean == 1' \
  "measured fixture changed timing reporting"
assert_json "$measured" '.run_summary.without_skill.pass_rate.mean == 0.5' \
  "measured fixture changed baseline reporting"
assert_json "$measured" '.run_summary.delta | .pass_rate == 0 and .tokens == 0 and .time_seconds == 0' \
  "measured fixture changed delta reporting"
assert_json "$measured" '.run_summary.with_skill.successful_assertions.total == 1' \
  "measured fixture omits successful assertion totals"
assert_json "$measured" '.run_summary.with_skill.token_efficiency == {"status":"measured","successful_assertions_per_1000_tokens":3.5714}' \
  "measured fixture reports incorrect token efficiency"
assert_json "$TEST_ROOT/measured-workspace/iteration-1/eval-one/with_skill/run-1/timing.json" \
  '.tokens == 280 and .cost_usd == 0.25 and .usage == {"input_tokens":120,"output_tokens":80,"cache_creation_input_tokens":30,"cache_read_input_tokens":50}' \
  "measured fixture omits complete usage evidence"

unavailable="$(run_fixture unavailable)"
assert_json "$unavailable" '.run_summary.with_skill.tokens == {"mean":null,"total":null,"measured_runs":0,"unavailable_runs":1}' \
  "unavailable fixture does not report missing token usage"
assert_json "$unavailable" '.run_summary.with_skill.token_efficiency == {"status":"unavailable","successful_assertions_per_1000_tokens":null}' \
  "unavailable fixture reports misleading token efficiency"

zero="$(run_fixture zero)"
assert_json "$zero" '.run_summary.with_skill.tokens == {"mean":0,"total":0,"measured_runs":1,"unavailable_runs":0}' \
  "zero fixture is not retained as measured usage"
assert_json "$zero" '.run_summary.with_skill.token_efficiency == {"status":"zero_tokens","successful_assertions_per_1000_tokens":null}' \
  "zero fixture is not distinguished from unavailable usage"

null_usage="$(run_fixture null)"
assert_json "$null_usage" '.run_summary.with_skill.tokens == {"mean":null,"total":null,"measured_runs":0,"unavailable_runs":1}' \
  "null token fields are not reported as unavailable"
assert_json "$null_usage" '.run_summary.with_skill.token_efficiency == {"status":"unavailable","successful_assertions_per_1000_tokens":null}' \
  "null token fields report misleading token efficiency"

failed="$(run_fixture failed)"
assert_json "$failed" '.run_summary.with_skill.tokens == {"mean":null,"total":null,"measured_runs":0,"unavailable_runs":1}' \
  "failed agent output aborts unavailable usage reporting"
assert_json "$TEST_ROOT/failed-workspace/iteration-1/eval-one/with_skill/run-1/timing.json" \
  '.tokens == null and .usage == {} and .cost_usd == null' \
  "failed agent output does not preserve empty usage evidence"

agent_timeout_workspace="$TEST_ROOT/agent-timeout-workspace"
PATH="$mock_bin:$PATH" MOCK_TOKEN_MODE=measured MOCK_AGENT_TIMEOUT=1 \
  "$RUNNER" "$skill_dir" --workspace "$agent_timeout_workspace" \
  --timeout-seconds 1 --no-baseline >/dev/null 2>&1
agent_timeout_run="$agent_timeout_workspace/iteration-1/eval-one/with_skill/run-1"
assert_json "$agent_timeout_run/timing.json" \
  '.outcome == "timed_out" and .exit_code == 142 and .timeout_seconds == 1' \
  "evaluated timeout evidence is missing"
assert_json "$agent_timeout_run/grading.json" \
  '.run_outcome == "timed_out" and .passed == 0' \
  "evaluated timeout is not distinguished from grading failures"
assert_json "$agent_timeout_workspace/iteration-1/benchmark.json" \
  '.run_summary.with_skill.outcomes.timed_out == 1' \
  "benchmark summary omits evaluated timeouts"
descendant_marker="$TEST_ROOT/surviving-descendant"
PATH="$mock_bin:$PATH" MOCK_TOKEN_MODE=measured MOCK_AGENT_TIMEOUT=1 \
  MOCK_DESCENDANT_MARKER="$descendant_marker" \
  "$RUNNER" "$skill_dir" --workspace "$TEST_ROOT/descendant-timeout-workspace" \
  --timeout-seconds 1 --no-baseline >/dev/null 2>&1
sleep 2
[[ ! -e "$descendant_marker" ]] ||
  fail "evaluated timeout left a surviving descendant"

judge_timeout_workspace="$TEST_ROOT/judge-timeout-workspace"
judge_timeout_log="$TEST_ROOT/judge-timeout.log"
if ! PATH="$mock_bin:$PATH" MOCK_TOKEN_MODE=measured MOCK_JUDGE_TIMEOUT=1 \
  "$RUNNER" "$skill_dir" --workspace "$judge_timeout_workspace" \
  --timeout-seconds 1 --no-baseline >/dev/null 2>"$judge_timeout_log"; then
  sed -n '1,120p' "$judge_timeout_log" >&2
  fail "judge timeout aborted the runner"
fi
judge_timeout_run="$judge_timeout_workspace/iteration-1/eval-one/with_skill/run-1"
assert_json "$judge_timeout_run/grading.json" \
  '.run_outcome == "completed" and .judge_outcome == "timed_out"' \
  "judge timeout evidence is missing"
assert_json "$judge_timeout_workspace/iteration-1/benchmark.json" \
  '.run_summary.with_skill.outcomes.judge_timed_out == 1' \
  "benchmark summary omits judge timeouts"

if PATH="$mock_bin:$PATH" MOCK_TOKEN_MODE=measured \
  "$RUNNER" "$skill_dir" --timeout-seconds 0 >/dev/null 2>&1; then
  fail "zero timeout succeeded"
fi

verified_skill_dir="$TEST_ROOT/verified-skill"
mkdir -p "$verified_skill_dir/evals/scripts"
printf '%s\n' '# Verified fixture skill' > "$verified_skill_dir/SKILL.md"
printf '%s\n' '{"skill_name":"verified-fixture","evals":[{"id":"verified","prompt":"test deterministic grading","assertions":["filesystem artifact exists","transcript assertion passes"],"setup_script":"evals/scripts/setup.sh","verification_script":"evals/scripts/verify.sh"}]}' \
  > "$verified_skill_dir/evals/evals.json"
cat > "$verified_skill_dir/evals/scripts/setup.sh" <<'SETUP'
#!/usr/bin/env bash
set -euo pipefail
[[ "$EVAL_ID" == verified ]]
[[ "$EVAL_CONFIG" == with_skill ]]
printf '%s\n' seeded > seeded.txt
SETUP
cat > "$verified_skill_dir/evals/scripts/verify.sh" <<'VERIFY'
#!/usr/bin/env bash
set -euo pipefail
if [[ -f filesystem-artifact.txt ]]; then
  printf '%s\n' '{"results":[{"assertion":"filesystem artifact exists","verdict":"PASS","evidence":"filesystem-artifact.txt exists"}]}'
else
  printf '%s\n' '{"results":[{"assertion":"filesystem artifact exists","verdict":"FAIL","evidence":"filesystem-artifact.txt is missing"}]}'
fi
VERIFY

verified_workspace="$TEST_ROOT/verified-workspace"
mock_args="$TEST_ROOT/verified-claude-args.txt"
sandbox_template="$TEST_ROOT/sandbox-template"
mkdir -p "$sandbox_template"
printf '%s\n' template > "$sandbox_template/template-input.txt"
PATH="$mock_bin:$PATH" MOCK_VERIFY_MODE=1 MOCK_ARGS_FILE="$mock_args" \
  "$RUNNER" "$verified_skill_dir" --workspace "$verified_workspace" \
  --sandbox-dir "$sandbox_template" --runs 2 --no-baseline \
  >/dev/null 2>&1
verified_run="$verified_workspace/iteration-1/eval-verified/with_skill/run-1"
assert_json "$verified_run/grading.json" \
  '.total == 2 and .passed == 2 and [.results[].assertion] == ["filesystem artifact exists","transcript assertion passes"]' \
  "deterministic and judge results were not merged"
assert_json "$verified_run/verification.json" \
  '.results == [{"assertion":"filesystem artifact exists","verdict":"PASS","evidence":"filesystem-artifact.txt exists"}]' \
  "filesystem verification evidence was not preserved"
assert_json "$verified_run/judge-grading.json" \
  '.results == [{"assertion":"transcript assertion passes","verdict":"PASS","evidence":"fixture output"}]' \
  "judge received deterministic assertions"
[[ -f "$verified_run/judge-raw.json" ]] || fail "judge raw output was not preserved"
grep -Fx -- '--disable-slash-commands' "$mock_args" >/dev/null || fail "evaluated run did not disable installed skills"
grep -Fx -- '--setting-sources' "$mock_args" >/dev/null || fail "evaluated run did not isolate setting sources"
grep -Fx -- 'project,local' "$mock_args" >/dev/null || fail "evaluated run used unexpected setting sources"
grep -Fx -- 'auto' "$mock_args" >/dev/null || fail "evaluated run did not enable safe automatic tools"
assert_json "$verified_workspace/iteration-1/eval-verified/with_skill/run-2/grading.json" \
  '.total == 2 and .passed == 2' \
  "sandbox template state leaked between runs"
assert_json "$verified_workspace/iteration-1/benchmark.json" \
  '.run_summary.with_skill.runs == 2' \
  "repeated deterministic runs were not aggregated"

selected_skill_dir="$TEST_ROOT/selected-skill"
selected_workspace="$TEST_ROOT/selected-workspace"
mkdir -p "$selected_skill_dir/evals"
printf '%s\n' '# Selected fixture skill' > "$selected_skill_dir/SKILL.md"
printf '%s\n' '{"skill_name":"selected-fixture","evals":[{"id":"one","prompt":"test","assertions":["first","second"]},{"id":"two","prompt":"test","assertions":["first","second"]}]}' \
  > "$selected_skill_dir/evals/evals.json"
PATH="$mock_bin:$PATH" MOCK_TOKEN_MODE=measured \
  "$RUNNER" "$selected_skill_dir" --workspace "$selected_workspace" \
  --eval two --no-baseline >/dev/null 2>&1
[[ ! -d "$selected_workspace/iteration-1/eval-one" ]] || \
  fail "evaluation selection ran an unselected case"
[[ -f "$selected_workspace/iteration-1/eval-two/with_skill/run-1/grading.json" ]] || \
  fail "evaluation selection skipped the requested case"
multi_workspace="$TEST_ROOT/multi-selected-workspace"
PATH="$mock_bin:$PATH" MOCK_TOKEN_MODE=measured \
  "$RUNNER" "$selected_skill_dir" --workspace "$multi_workspace" \
  --eval one --eval two --no-baseline >/dev/null 2>&1
assert_json "$multi_workspace/iteration-1/benchmark.json" \
  '.run_summary.with_skill.runs == 2' \
  "repeatable evaluation selection omitted a requested case"
if PATH="$mock_bin:$PATH" MOCK_TOKEN_MODE=measured \
  "$RUNNER" "$selected_skill_dir" --workspace "$TEST_ROOT/missing-workspace" \
  --eval missing --no-baseline >/dev/null 2>&1; then
  fail "unknown evaluation selection succeeded"
fi

echo "output eval fixtures passed"
