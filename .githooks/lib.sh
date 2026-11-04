#!/bin/sh

ensure_venv() {
    [ -d .venv ] || uv sync --locked --offline --all-packages --all-groups || {
        echo "Hook setup failed: offline uv sync could not create .venv." >&2
        return 1
    }
}

run_tool() {
    ensure_venv || return 1
    set -f
    set -- ${VARDE_HOOKS_TOOL_PREFIX:-uv run --locked --no-sync --all-packages} "$@"
    "$@"
}

run_tool_xargs() {
    ensure_venv || return 1
    set -f
    set -- ${VARDE_HOOKS_TOOL_PREFIX:-uv run --locked --no-sync --all-packages} "$@"
    xargs -0 "$@"
}

run_ruff_xargs() {
    if ! ensure_venv; then
        echo "Skipping ruff: the hook sandbox cannot provide its offline environment." >&2
        return 0
    fi
    output=$(mktemp)
    if run_tool ruff --version >"$output" 2>&1; then
        rm -f "$output"
        run_tool_xargs "$@"
        return $?
    fi
    if grep -Eiq 'failed to spawn.*ruff|ruff: (not found|command not found)|no such file or directory.*ruff' "$output"; then
        rm -f "$output"
        echo "Skipping ruff: neither the hook venv nor uv can provide ruff in this sandbox." >&2
        return 0
    fi
    cat "$output" >&2
    rm -f "$output"
    return 1
}

validate_stage() {
    case "$1" in
        pre-commit|pre-merge-commit|pre-push) ;;
        *) echo "Invalid .githooks/pyright-stage: '$1' (expected pre-commit, pre-merge-commit, or pre-push)." >&2; return 1 ;;
    esac
}

run_pyright_at_stage() {
    current_stage=$1
    matched_stage=0
    set -f
    for configured_stage in $(cat .githooks/pyright-stage); do
        validate_stage "$configured_stage" || return 1
        [ "$configured_stage" = "$current_stage" ] && matched_stage=1
    done
    if [ "$matched_stage" -eq 1 ]; then
        run_tool pyright
    fi
}

fire_guardrail() {
    guardrail_id=$1
    shift
    command -v varde >/dev/null 2>&1 || return 0
    (varde learn sessions fire "$guardrail_id" "$@" >/dev/null 2>&1 || true) \
        </dev/null >/dev/null 2>&1 &
}

record_guardrail_on_exit() {
    guardrail_id=$1
    trap 'guardrail_status=$?; if [ -n "${guardrail_cleanup_path:-}" ]; then rm -f "$guardrail_cleanup_path"; fi; if [ "$guardrail_status" -eq 0 ]; then fire_guardrail "$guardrail_id"; else fire_guardrail "$guardrail_id" --blocked; fi; exit "$guardrail_status"' EXIT
}

# A merge that brings in commits of a plan needs the user's approval record, the
# same one `varde plan merge` checks. The hook sees the merge command line
# (GIT_REFLOG_ACTION; MERGE_HEAD is not written yet), resolves each revision to a
# commit and lets `varde plan merge-gate` match plans by branch content, so renamed
# branches, tags and commit ids are covered. Not seen: fast-forward merges (git runs
# no merge hook), `--no-verify`, squash merges and merges where git sets another
# action name. Without `varde` on PATH the merge is blocked. With the runner
# switch off (the default) `varde plan merge-gate` skips the check and exits 0.
# `varde plan merged` and conclude report those afterwards.
require_plan_merge_approval() {
    set -f
    revs=
    first=1
    for word in ${GIT_REFLOG_ACTION:-}; do
        if [ "$first" -eq 1 ]; then first=0; continue; fi
        case "$word" in -*) continue ;; esac
        revs="$revs $word"
    done
    [ -n "$revs" ] || return 0
    command -v varde >/dev/null 2>&1 || {
        echo "Merge blocked: varde is needed to check plan approvals." >&2
        return 1
    }
    # shellcheck disable=SC2086 - revisions are split on purpose.
    varde plan merge-gate $revs || {
        echo "Merge blocked: a plan in this merge has no user merge approval." >&2
        return 1
    }
}

check_new_main_commits() {
    range=$1
    [ -n "$range" ] || return 0
    command -v varde >/dev/null 2>&1 || {
        echo "Merge approval check unavailable: varde is not on PATH." >&2
        return 1
    }
    case "$range" in
        new:*) commits=${range#new:} ;;
        *)
            parents=$(git rev-list --reverse --first-parent --parents "$range") || return 1
            commits=$(printf '%s\n' "$parents" | awk '{ if (NF > 2) { for (i=3; i<=NF; i++) print $i } else print $1 }')
            ;;
    esac
    [ -n "$commits" ] || return 0
    # One call checks the first-parent commits introduced by a merge or fast-forward.
    # shellcheck disable=SC2086 - revisions are split on purpose.
    varde plan merge-gate --mode backstop $commits
}
