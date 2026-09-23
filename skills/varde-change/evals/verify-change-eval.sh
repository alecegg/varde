#!/usr/bin/env bash
set -euo pipefail

verdict() {
  if "$@"; then
    printf PASS
  else
    printf FAIL
  fi
}

one_plan_exists() {
  [[ "$(find memory-bank/working/plans -name plan.md -type f 2>/dev/null | wc -l | tr -d ' ')" == 1 ]]
}

plan_has_seed_sections() {
  local plan_file
  plan_file="$(find memory-bank/working/plans -name plan.md -type f -print -quit 2>/dev/null)"
  [[ -n "$plan_file" ]] || return 1
  grep -Fq '## Problem' "$plan_file" &&
    grep -Fq '## Solution' "$plan_file" &&
    grep -Fq '## Acceptance criteria' "$plan_file"
}

path_is_clean() {
  [[ -z "$(git status --porcelain -- "$1")" ]]
}

repository_artifacts_are_clean() {
  path_is_clean memory-bank && path_is_clean src
}

all_tasks_done() {
  local task
  while IFS= read -r task; do
    grep -Eq '^status:[[:space:]]*done[[:space:]]*$' "$task" || return 1
  done < <(find memory-bank/working/plans -path '*/tasks/*.md' -type f)
}

all_criteria_checked() {
  local plan_file="$1"
  awk '
    /^## Acceptance criteria/ {inside=1; next}
    inside && /^## / {inside=0}
    inside && /^- \[ \]/ {unchecked=1}
    END {exit(unchecked ? 1 : 0)}
  ' "$plan_file"
}

first_line_matching() {
  local pattern="$1"
  local transcript="$2"
  grep -Einm1 "$pattern" "$transcript" 2>/dev/null | cut -d: -f1 || true
}

evidence_precedes_implementation() {
  local transcript="$1"
  local reproduction hypotheses experiments implementation
  reproduction="$(first_line_matching 'reproduction:|reproduce|phase 1' "$transcript")"
  hypotheses="$(first_line_matching 'hypotheses:' "$transcript")"
  experiments="$(first_line_matching 'experiments:' "$transcript")"
  implementation="$(first_line_matching 'implementation begins|implementing the fix|apply the fix|fix applied|phase 5' "$transcript")"
  [[ -n "$reproduction" && -n "$hypotheses" && -n "$experiments" &&
     -n "$implementation" &&
     "$reproduction" -lt "$hypotheses" &&
     "$hypotheses" -lt "$experiments" &&
     "$experiments" -lt "$implementation" ]]
}

evidence_follows_implementation() {
  local transcript="$1"
  local implementation cause verification
  implementation="$(first_line_matching 'implementation begins|implementing the fix|apply the fix|fix applied|phase 5' "$transcript")"
  cause="$(first_line_matching 'cause:' "$transcript")"
  verification="$(first_line_matching 'verification:' "$transcript")"
  [[ -n "$implementation" && -n "$cause" && -n "$verification" &&
     "$implementation" -lt "$cause" &&
     "$cause" -lt "$verification" ]]
}

case "$EVAL_ID" in
  1)
    transcript="$EVAL_RUN_DIR/transcript.txt"
    routed="FAIL"
    if grep -Eiq 'references/status\.md|status mode' "$transcript" 2>/dev/null; then
      routed="PASS"
    fi
    disk="FAIL"
    if grep -Fq '2026-09-18-active' "$transcript" 2>/dev/null &&
       grep -Fq '2026-09-19-open' "$transcript" 2>/dev/null; then
      disk="PASS"
      routed="PASS"
    fi
    unchanged="$(verdict path_is_clean memory-bank)"
    next_mode="FAIL"
    if grep -Eiq 'recommended next mode.*(plan|build|orchestrate|verify)' \
       "$transcript" 2>/dev/null; then
      next_mode="PASS"
    fi
    jq -n --arg routed "$routed" --arg disk "$disk" \
      --arg unchanged "$unchanged" --arg next_mode "$next_mode" '{results:[
      {
        assertion:"Routes to status mode without asking the user to choose a mode",
        verdict:$routed,
        evidence:(if $routed == "PASS" then "status output matches both seeded disk artifacts" else "status output omits seeded disk artifacts" end)
      },
      {
        assertion:"Derives status from files on disk, not from conversation memory or inference",
        verdict:$disk,
        evidence:(if $disk == "PASS" then "transcript reports both seeded artifacts" else "transcript omits seeded disk artifacts" end)
      },
      {
        assertion:"Leaves every plan, task, and handoff file byte-identical",
        verdict:$unchanged,
        evidence:(if $unchanged == "PASS" then "git status reports no memory-bank changes" else "git status reports memory-bank changes" end)
      },
      {
        assertion:"Recommends exactly one next mode and stops there rather than running it",
        verdict:$next_mode,
        evidence:(if $next_mode == "PASS" then "transcript recommends one next mode" else "transcript does not recommend exactly one next mode" end)
      }
    ]}'
    ;;
  2)
    transcript="$EVAL_RUN_DIR/transcript.txt"
    routed="FAIL"
    if grep -Eiq 'references/plan\.md|plan mode' "$transcript" 2>/dev/null; then
      routed="PASS"
    fi
    seeded="$(verdict plan_has_seed_sections)"
    one_file="FAIL"
    if one_plan_exists &&
       [[ "$(find memory-bank/working/plans -type f 2>/dev/null | wc -l | tr -d ' ')" == 1 ]] &&
       ! find memory-bank/working/plans -type d -name tasks -print -quit 2>/dev/null | grep -q . &&
       ! grep -Fq '## Tasks' "$(find memory-bank/working/plans -name plan.md -type f -print -quit)"; then
      one_file="PASS"
    fi
    source_unchanged="$(verdict path_is_clean src)"
    if [[ "$seeded" == "PASS" && "$one_file" == "PASS" &&
          "$source_unchanged" == "PASS" ]]; then
      routed="PASS"
    fi
    inline_menu="FAIL"
    if grep -Eq '^[[:space:]]*1[.)][[:space:]]' "$transcript" 2>/dev/null &&
       grep -Eiq 'recommendation:|my recommendation' "$transcript" 2>/dev/null; then
      inline_menu="PASS"
    fi
    jq -n --arg routed "$routed" --arg seeded "$seeded" \
      --arg one_file "$one_file" --arg source_unchanged "$source_unchanged" \
      --arg inline_menu "$inline_menu" '{results:[
        {
          assertion:"Routes to plan mode, not build mode, and does not ask the user which mode to use",
          verdict:$routed,
        evidence:(if $routed == "PASS" then "plan artifacts prove planning behavior" else "plan artifacts do not prove planning behavior" end)
        },
        {
          assertion:"Creates plan.md seeded with a best guess before asking the first question",
          verdict:$seeded,
          evidence:(if $seeded == "PASS" then "plan.md contains Problem, Solution, and Acceptance criteria" else "plan.md is missing required seed sections" end)
        },
        {
          assertion:"Produces exactly one file \u2014 plan.md \u2014 with no ## Tasks section and no tasks/ files",
          verdict:$one_file,
          evidence:(if $one_file == "PASS" then "exactly one plan.md exists without task artifacts" else "unexpected plan or task artifacts exist" end)
        },
        {
          assertion:"Changes no production source during planning",
          verdict:$source_unchanged,
          evidence:(if $source_unchanged == "PASS" then "git status reports no src changes" else "git status reports src changes" end)
        },
        {
          assertion:"Asks questions inline as a numbered menu, not via a native question-prompt tool",
          verdict:$inline_menu,
          evidence:(if $inline_menu == "PASS" then "transcript contains numbered options and a recommendation" else "transcript omits the inline question format" end)
        }
      ]}'
    ;;
  3)
    transcript="$EVAL_RUN_DIR/transcript.txt"
    routed="FAIL"
    if grep -Eiq 'references/build\.md|build mode' "$transcript" 2>/dev/null; then
      routed="PASS"
    fi
    implemented="FAIL"
    if grep -Eq 'Math\.random|random' src/queue/worker.ts 2>/dev/null &&
       grep -Eq 'Math\.pow|\*\*|exponential' src/queue/worker.ts 2>/dev/null; then
      implemented="PASS"
    fi
    verified="FAIL"
    if grep -Eiq 'test|check|verif' "$transcript" 2>/dev/null; then
      verified="PASS"
    fi
    plans_unchanged="$(verdict path_is_clean memory-bank)"
    source_changed="FAIL"
    if ! path_is_clean src; then
      source_changed="PASS"
    fi
    if [[ "$implemented" == "PASS" && "$plans_unchanged" == "PASS" &&
          "$source_changed" == "PASS" ]]; then
      routed="PASS"
    fi
    jq -n --arg routed "$routed" --arg implemented "$implemented" \
      --arg verified "$verified" --arg plans_unchanged "$plans_unchanged" \
      --arg source_changed "$source_changed" '{results:[
      {
        assertion:"Routes to build mode, not plan mode, for a concrete bounded change",
        verdict:$routed,
        evidence:(if $routed == "PASS" then "source and plan state prove direct build behavior" else "source and plan state do not prove direct build behavior" end)
      },
      {
        assertion:"Implements exponential backoff with jitter in src/queue/worker.ts",
        verdict:$implemented,
        evidence:(if $implemented == "PASS" then "worker source contains exponential jitter" else "worker source omits exponential jitter" end)
      },
      {
        assertion:"Runs a narrow verification for the changed retry behavior",
        verdict:$verified,
        evidence:(if $verified == "PASS" then "transcript reports verification" else "transcript omits verification" end)
      },
      {
        assertion:"Creates no plan or task artifacts for the micro-change",
        verdict:$plans_unchanged,
        evidence:(if $plans_unchanged == "PASS" then "git status reports no memory-bank changes" else "git status reports memory-bank changes" end)
      },
      {
        assertion:"Changes production source directly for the requested micro-change",
        verdict:$source_changed,
        evidence:(if $source_changed == "PASS" then "git status reports src changes" else "git status reports no src changes" end)
      }
    ]}'
    ;;
  4)
    transcript="$EVAL_RUN_DIR/transcript.txt"
    routed="FAIL"
    if grep -Eiq 'references/verify\.md|verify mode|verification mode' "$transcript" 2>/dev/null; then
      routed="PASS"
    fi
    graded="FAIL"
    if grep -Fq 'test -f src/manage.ts' "$transcript" 2>/dev/null &&
       grep -Fq 'export function manage' "$transcript" 2>/dev/null; then
      graded="PASS"
    fi
    unchanged="$(verdict path_is_clean memory-bank)"
    if [[ "$graded" == "PASS" && "$unchanged" == "PASS" ]]; then
      routed="PASS"
    fi
    separated="FAIL"
    if grep -Eiq 'unavailable' "$transcript" 2>/dev/null &&
       grep -Eiq 'fail' "$transcript" 2>/dev/null; then
      separated="PASS"
    fi
    recommends="FAIL"
    if grep -Eiq 'varde-change build' "$transcript" 2>/dev/null; then
      recommends="PASS"
    fi
    jq -n --arg routed "$routed" --arg graded "$graded" \
      --arg unchanged "$unchanged" --arg separated "$separated" \
      --arg recommends "$recommends" '{results:[
      {
        assertion:"Routes to verify mode, not build mode, for a request asking for evidence rather than fixes",
        verdict:$routed,
        evidence:(if $routed == "PASS" then "criterion evidence and clean plans prove verification behavior" else "results do not prove verification behavior" end)
      },
      {
        assertion:"Grades against each criterion\u0027s assert:/retrieve: clause rather than trusting the checkbox state",
        verdict:$graded,
        evidence:(if $graded == "PASS" then "transcript reports assertion and retrieval evidence" else "transcript omits criterion evidence" end)
      },
      {
        assertion:"Leaves plan.md acceptance checkboxes and every task status exactly as found",
        verdict:$unchanged,
        evidence:(if $unchanged == "PASS" then "git status reports no memory-bank changes" else "git status reports memory-bank changes" end)
      },
      {
        assertion:"Separates unavailable evidence from failed criteria instead of reporting both as failures",
        verdict:$separated,
        evidence:(if $separated == "PASS" then "transcript reports unavailable and failed outcomes" else "transcript does not separate unavailable and failed outcomes" end)
      },
      {
        assertion:"Recommends varde-change build if fixes are needed rather than making them",
        verdict:$recommends,
        evidence:(if $recommends == "PASS" then "transcript recommends varde-change build" else "transcript omits the build recommendation" end)
      }
    ]}'
    ;;
  5)
    unchanged="$(verdict repository_artifacts_are_clean)"
    jq -n --arg verdict "$unchanged" '{results:[{
      assertion:"Leaves group plans and production source unchanged before selection",
      verdict:$verdict,
      evidence:(if $verdict == "PASS" then "git status reports no memory-bank or src changes" else "git status reports repository changes" end)
    }]}'
    ;;
  7)
    transcript="$EVAL_RUN_DIR/transcript.txt"
    ordered="FAIL"
    if grep -Eiq 'schema.*(before|then|→|->).*delivery' "$transcript" 2>/dev/null; then
      ordered="PASS"
    fi

    delegated="FAIL"
    if grep -Eiq 'sequential|one at a time' "$transcript" 2>/dev/null &&
       grep -Eiq 'varde-change build|build mode' "$transcript" 2>/dev/null; then
      delegated="PASS"
    fi

    stopped="FAIL"
    if grep -Eiq 'fail|block' "$transcript" 2>/dev/null &&
       grep -Eiq 'stop immediately|halt immediately|stop there' "$transcript" 2>/dev/null &&
       grep -Eiq "no later|without running later|do not run later|no .*delivery|delivery[^[:alnum:]]+(does not|doesn't) run" "$transcript" 2>/dev/null; then
      stopped="PASS"
    fi

    unchanged="$(verdict repository_artifacts_are_clean)"
    jq -n --arg ordered "$ordered" --arg delegated "$delegated" \
      --arg stopped "$stopped" --arg unchanged "$unchanged" '{results:[
        {
          assertion:"Orders the schema child before delivery using the declared dependency",
          verdict:$ordered,
          evidence:(if $ordered == "PASS" then "transcript names schema before delivery" else "transcript does not establish schema before delivery" end)
        },
        {
          assertion:"Delegates child plans sequentially through varde-change build",
          verdict:$delegated,
          evidence:(if $delegated == "PASS" then "transcript names sequential varde-change build delegation" else "transcript omits sequential build delegation" end)
        },
        {
          assertion:"Stops immediately after a failed child without running later children",
          verdict:$stopped,
          evidence:(if $stopped == "PASS" then "transcript stops immediately without later children" else "transcript omits immediate failure stopping" end)
        },
        {
          assertion:"Leaves group plans and production source unchanged during the walkthrough",
          verdict:$unchanged,
          evidence:(if $unchanged == "PASS" then "git status reports no memory-bank or src changes" else "git status reports repository changes" end)
        }
    ]}'
    ;;
  8)
    plan_file="memory-bank/working/plans/2026-09-20-retry-policy/plan.md"
    named_plan="FAIL"
    if one_plan_exists && [[ -f "$plan_file" ]]; then
      named_plan="PASS"
    fi

    decomposed="FAIL"
    if find memory-bank/working/plans/2026-09-20-retry-policy/tasks \
      -name '*.md' -type f -print -quit 2>/dev/null | grep -q .; then
      decomposed="PASS"
    fi

    implemented="FAIL"
    if [[ -f src/retry-policy.ts ]] &&
       grep -Eq 'return[[:space:]]+5' src/retry-policy.ts; then
      implemented="PASS"
    fi

    completed="FAIL"
    if grep -Eq '^status:[[:space:]]*completed[[:space:]]*$' "$plan_file" &&
       [[ "$decomposed" == "PASS" ]] && all_tasks_done; then
      completed="PASS"
    fi

    checked="$(verdict all_criteria_checked "$plan_file")"
    jq -n --arg named_plan "$named_plan" --arg decomposed "$decomposed" \
      --arg implemented "$implemented" --arg completed "$completed" \
      --arg checked "$checked" '{results:[
        {
          assertion:"Builds the named existing plan without creating a replacement plan",
          verdict:$named_plan,
          evidence:(if $named_plan == "PASS" then "the named plan remains the only plan" else "the named plan is missing or another plan exists" end)
        },
        {
          assertion:"Decomposes the plan specification into task files before implementation",
          verdict:$decomposed,
          evidence:(if $decomposed == "PASS" then "the named plan contains task files" else "the named plan contains no task files" end)
        },
        {
          assertion:"Creates src/retry-policy.ts with maxAttempts returning 5",
          verdict:$implemented,
          evidence:(if $implemented == "PASS" then "retry policy source returns 5" else "retry policy source is missing or incorrect" end)
        },
        {
          assertion:"Marks every generated task done and the plan completed",
          verdict:$completed,
          evidence:(if $completed == "PASS" then "plan and task statuses are terminal" else "plan or task statuses remain incomplete" end)
        },
        {
          assertion:"Verifies and checks every plan acceptance criterion",
          verdict:$checked,
          evidence:(if $checked == "PASS" then "no unchecked acceptance criteria remain" else "unchecked acceptance criteria remain" end)
        }
      ]}'
    ;;
  9)
    transcript="$EVAL_RUN_DIR/transcript.txt"
    routed="FAIL"
    if grep -Eiq '^[[:space:]]*debug_mode:[[:space:]]*fix[[:space:]]*$' \
      "$transcript" 2>/dev/null; then
      routed="PASS"
    fi
    automatic="FAIL"
    if grep -Eiq '^[[:space:]]*route_source:[[:space:]]*automatic[[:space:]]*$' \
      "$transcript" 2>/dev/null; then
      automatic="PASS"
    fi
    before="FAIL"
    if evidence_precedes_implementation "$transcript"; then
      before="PASS"
    fi
    after="FAIL"
    if evidence_follows_implementation "$transcript"; then
      after="PASS"
    fi
    changed="FAIL"
    if ! path_is_clean src; then
      changed="PASS"
    fi
    if [ "$automatic" != "PASS" ]; then
      routed="FAIL"
    fi
    jq -n --arg routed "$routed" --arg before "$before" \
      --arg after "$after" --arg changed "$changed" '{results:[
      {
        assertion:"Routes a named regression to references/debugging-entry.md without an explicit mode",
        verdict:$routed,
        evidence:(if $routed == "PASS" then "transcript names automatic debugging entry" else "transcript omits debugging entry" end)
      },
      {
        assertion:"Records reproduction, hypotheses, and experiments before implementation",
        verdict:$before,
        evidence:(if $before == "PASS" then "debug evidence precedes implementation" else "debug evidence ordering is incomplete" end)
      },
      {
        assertion:"Records cause and verification after the fix",
        verdict:$after,
        evidence:(if $after == "PASS" then "cause and verification follow implementation" else "post-fix evidence ordering is incomplete" end)
      },
      {
        assertion:"Changes the seeded source after the evidence gate",
        verdict:$changed,
        evidence:(if $changed == "PASS" then "git status reports source changes" else "source remains unchanged" end)
      }
    ]}'
    ;;
  10)
    transcript="$EVAL_RUN_DIR/transcript.txt"
    routed="FAIL"
    if grep -Eiq '^[[:space:]]*debug_mode:[[:space:]]*diagnose[[:space:]]*$' \
      "$transcript" 2>/dev/null; then
      routed="PASS"
    fi
    explicit="FAIL"
    if grep -Eiq '^[[:space:]]*route_source:[[:space:]]*explicit[[:space:]]*$' \
      "$transcript" 2>/dev/null; then
      explicit="PASS"
    fi
    unchanged="$(verdict path_is_clean src)"
    hypotheses="FAIL"
    if grep -Eiq 'reproduction' "$transcript" 2>/dev/null &&
       grep -Eiq 'hypotheses' "$transcript" 2>/dev/null &&
       grep -Eiq 'experiments' "$transcript" 2>/dev/null; then
      hypotheses="PASS"
    fi
    limits="FAIL"
    if grep -Eiq 'evidence limit|cannot confirm|uncertain' "$transcript" 2>/dev/null &&
       grep -Eiq 'no fix|without (a )?fix|did not (apply|make|implement).*fix|diagnos(is|e).*(only|without)' \
         "$transcript" 2>/dev/null; then
      limits="PASS"
    fi
    if [ "$explicit" != "PASS" ]; then
      routed="FAIL"
    fi
    jq -n --arg routed "$routed" --arg unchanged "$unchanged" \
      --arg hypotheses "$hypotheses" --arg limits "$limits" '{results:[
      {
        assertion:"Honors explicit diagnosis-only mode over automatic bug routing",
        verdict:$routed,
        evidence:(if $routed == "PASS" then "transcript names diagnosis mode" else "transcript omits diagnosis mode" end)
      },
      {
        assertion:"Leaves production source unchanged",
        verdict:$unchanged,
        evidence:(if $unchanged == "PASS" then "git status reports no source changes" else "git status reports source changes" end)
      },
      {
        assertion:"Reports reproduction and tested hypotheses",
        verdict:$hypotheses,
        evidence:(if $hypotheses == "PASS" then "reproduction and experiments appear in transcript" else "reproduction or tested hypotheses are missing" end)
      },
      {
        assertion:"States evidence limits without claiming a fix",
        verdict:$limits,
        evidence:(if $limits == "PASS" then "transcript states diagnosis limits" else "diagnosis limits are missing" end)
      }
    ]}'
    ;;
  11)
    transcript="$EVAL_RUN_DIR/transcript.txt"
    explored="FAIL"
    if grep -Eiq 'varde-explore|exploration' "$transcript" 2>/dev/null &&
       ! grep -Eiq 'references/debugging-entry\.md|debug_mode:' "$transcript" 2>/dev/null; then
      explored="PASS"
    fi
    unchanged="$(verdict path_is_clean src)"
    jq -n --arg explored "$explored" --arg unchanged "$unchanged" '{results:[
      {
        assertion:"Honors explicit exploration over automatic debugging routing",
        verdict:$explored,
        evidence:(if $explored == "PASS" then "transcript names exploration without debug mode" else "transcript does not prove exploration precedence" end)
      },
      {
        assertion:"Names varde-explore as the owning workflow",
        verdict:$explored,
        evidence:(if $explored == "PASS" then "transcript names varde-explore" else "transcript omits varde-explore" end)
      },
      {
        assertion:"Leaves production source unchanged",
        verdict:$unchanged,
        evidence:(if $unchanged == "PASS" then "git status reports no source changes" else "git status reports source changes" end)
      }
    ]}'
    ;;
  12)
    transcript="$EVAL_RUN_DIR/transcript.txt"
    built="FAIL"
    if grep -Eiq 'references/build\.md|build mode|explicit build' "$transcript" 2>/dev/null &&
       ! grep -Eiq 'references/debugging-entry\.md|debug_mode:' "$transcript" 2>/dev/null; then
      built="PASS"
    fi
    changed="FAIL"
    if [[ ! "$(git status --porcelain -- src)" == "" ]] &&
       grep -Eq 'return[[:space:]]+"fixed"' src/parser.ts 2>/dev/null; then
      changed="PASS"
    fi
    verified="FAIL"
    if grep -Eiq 'test|check|verif' "$transcript" 2>/dev/null; then
      verified="PASS"
    fi
    jq -n --arg built "$built" --arg changed "$changed" --arg verified "$verified" '{results:[
      {
        assertion:"Honors explicit build over automatic debugging routing",
        verdict:$built,
        evidence:(if $built == "PASS" then "transcript names normal build without debug mode" else "transcript does not prove build precedence" end)
      },
      {
        assertion:"Changes the seeded parser source directly",
        verdict:$changed,
        evidence:(if $changed == "PASS" then "parser source returns fixed" else "parser source is unchanged or incorrect" end)
      },
      {
        assertion:"Runs a focused verification",
        verdict:$verified,
        evidence:(if $verified == "PASS" then "transcript reports verification" else "transcript omits verification" end)
      }
    ]}'
    ;;
  *)
    printf 'unsupported change eval id: %s\n' "$EVAL_ID" >&2
    exit 2
    ;;
esac
