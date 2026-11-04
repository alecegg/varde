default:
    @just --list

PEX_BUILDER := "app/pex/build.py"

# Run every Python test, the fast shell tier, and imported repository checks.
test tier="fast":
    #!/usr/bin/env bash
    set -eu
    just lint
    source ./core/scripts/test-env.sh
    export UV_OFFLINE=1
    uv sync --locked --offline --all-packages --all-groups
    python3 core/scripts/test-baseline.sh --install-prerequisites
    log_dir=$(mktemp -d)
    pids=()
    packages=()
    logs=()
    projects=()
    all_modules=($(python3 core/scripts/select_changed_test_modules.py --list))
    for package in "${all_modules[@]}"; do
        test -f "$package/pyproject.toml" || { echo "Missing module: $package" >&2; exit 1; }
        test -d "$package/tests" || { echo "Missing tests: $package" >&2; exit 1; }
        compgen -G "$package/tests/test_*.py" >/dev/null || compgen -G "$package/tests/*_test.py" >/dev/null || { echo "No pytest files: $package" >&2; exit 1; }
        projects+=("$package")
    done
    # Shell tests take minutes under load, so start them beside the pytest jobs
    # rather than serially (after uv sync, which owns the venv). The runner
    # prints one PASS/FAIL/SKIP line per script, so its whole log is printed.
    shell_log="$log_dir/test-shell.log"
    just test-shell {{ tier }} >"$shell_log" 2>&1 &
    shell_pid=$!
    for package in "${projects[@]}"; do
        log="$log_dir/$(basename "$package").log"
        uv run --offline --no-sync pytest "$package/tests" -q >"$log" 2>&1 &
        pids+=("$!")
        packages+=("$package")
        logs+=("$log")
    done
    # Tests outside a module's tests/ directory (dev/, code/bench/, runner/bench/): add one "label: command" line.
    extras=(
        "dev-quiet-check: uv run --offline --no-sync pytest dev/tests/test_quiet_check.py -q"
        "dev-prototype-verifier: bash dev/tests/prototype-verifier.sh"
        "dev-explain-verifier: bash dev/tests/explain-verifier.sh"
        "dev-pr-skill: bash dev/tests/pr-skill.sh"
    )
    for extra in "${extras[@]}"; do
        log="$log_dir/${extra%%:*}.log"
        bash -c "${extra#*: }" >"$log" 2>&1 &
        pids+=("$!")
        packages+=("${extra%%:*}")
        logs+=("$log")
    done
    failed=0
    for index in "${!pids[@]}"; do
        if wait "${pids[$index]}"; then
            echo "PASS ${packages[$index]}: $(tail -n 1 "${logs[$index]}")"
        else
            cat "${logs[$index]}"
            echo "FAIL ${packages[$index]}" >&2
            failed=1
        fi
    done
    shell_status=0
    wait "$shell_pid" || shell_status=$?
    cat "$shell_log"
    if [ "$shell_status" -ne 0 ]; then
        echo "FAIL test-shell" >&2
        failed=1
    fi
    if [ "$failed" -ne 0 ]; then
        exit 1
    fi
    varde scan --report --repo-root .
    ./core/scripts/check-refs.sh
    just test-agents

# Run every Python test and both shell-test tiers.
test-all:
    just test all

# Sync Python dependencies and build/check runner UI before tests when their sources change.
test-prep:
    #!/usr/bin/env bash
    set -euo pipefail
    source ./core/scripts/test-env.sh
    export UV_OFFLINE=1
    uv sync --locked --offline --all-packages --all-groups
    python3 core/scripts/test-baseline.sh --install-prerequisites

# Run non-slow pytest tests; optional module names limit the run, and no names means all modules.
# Uses two xdist workers for core, code, workflow, and data; other modules run serially.
test-fast *modules:
    #!/usr/bin/env bash
    set -euo pipefail
    source ./core/scripts/test-env.sh
    export UV_OFFLINE=1
    uv sync --locked --offline --all-packages --all-groups
    log_dir=$(mktemp -d)
    pids=()
    requested_modules=({{ modules }})
    all_modules=($(python3 core/scripts/select_changed_test_modules.py --list))
    if [ "${#requested_modules[@]}" -eq 0 ]; then
        packages=("${all_modules[@]}")
    else
        packages=("${requested_modules[@]}")
        for package in "${packages[@]}"; do
            if [[ " ${all_modules[*]} " != *" $package "* ]]; then
                echo "Unknown module: $package" >&2
                exit 2
            fi
        done
    fi
    for package in "${packages[@]}"; do
        test -f "$package/pyproject.toml" || { echo "Missing module: $package" >&2; exit 1; }
        test -d "$package/tests" || { echo "Missing tests: $package" >&2; exit 1; }
        xdist_workers=0
        case "$package" in
            core|code|workflow|data) xdist_workers=2 ;;
        esac
        if [ "$xdist_workers" -gt 0 ]; then
            uv run --offline --no-sync pytest "$package/tests" -q -m 'not slow' -n "$xdist_workers" >"$log_dir/$package.log" 2>&1 &
        else
            uv run --offline --no-sync pytest "$package/tests" -q -m 'not slow' >"$log_dir/$package.log" 2>&1 &
        fi
        pids+=("$!")
    done
    failed=0
    for index in "${!pids[@]}"; do
        if wait "${pids[$index]}"; then
            echo "PASS ${packages[$index]}: $(tail -n 1 "$log_dir/${packages[$index]}.log")"
        else
            cat "$log_dir/${packages[$index]}.log"
            echo "FAIL ${packages[$index]}" >&2
            failed=1
        fi
    done
    exit "$failed"

# Run non-slow tests for changed modules and transitive dependents from the merge-base with main.
test-changed:
    #!/usr/bin/env bash
    set -euo pipefail
    modules=$(python3 core/scripts/select_changed_test_modules.py)
    printf 'Changed modules: %s\n' "$modules"
    just test-fast $modules
    if [[ " $modules " != *" core "* ]]; then
        uv run pytest core/tests/test_dependency_rules.py -q
    fi

# Slow Python tests use `@pytest.mark.slow`; run a module's slow cases with
# `uv run pytest <module>/tests -m slow`, or run all Python tests with `just test`.
# Run all module pytest tests under core/scripts/test-env.sh, including slow tests.
test-baseline:
    ./core/scripts/test-baseline.sh

# Refresh stale repo-map packs and commit docs/repo-map/ (main checkout only; skips elsewhere).
repo-map-refresh:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f .git ]; then echo "repo-map-refresh: skipped (linked worktree; run on the main checkout)"; exit 0; fi
    if [ ! -d docs/repo-map ]; then echo "repo-map-refresh: skipped (no docs/repo-map/)"; exit 0; fi
    if ! varde map packs build --help 2>&1 | grep -q -- '--stale'; then
        echo "repo-map-refresh: skipped (installed varde lacks 'map packs build --stale'; redeploy the CLI)"
        exit 0
    fi
    varde map packs build --stale
    if [ -z "$(git status --porcelain -- docs/repo-map)" ]; then exit 0; fi
    git add -- docs/repo-map
    git commit -m "Refresh repo map packs" -- docs/repo-map

build-ui:
    npm ci --prefix runner/ui
    npm run build --prefix runner/ui

test-webkit:
    source ./core/scripts/test-env.sh
    npm ci --ignore-scripts --prefix runner/ui
    bash runner/scripts/install-webkit-browsers.sh
    npm run test:webkit-viewport --prefix runner/ui

test-agents:
    uv run --locked python app/scripts/generate.py --check
    app/tests/agents/run-all.sh
    workflow/tests/agents/run-all.sh

test-shell tier="all":
    ./core/scripts/run-shell-tests.sh --tier {{ tier }}

# Run Ruff lint and formatting checks for all workspace packages.
lint:
    uv run --locked --all-packages ruff check
    uv run --locked --all-packages ruff format --check
    core/scripts/check-ruff-baseline.sh
    # The first run fetches npm Pyright; CI runners need npm registry access.
    uv run --locked --all-packages pyright

test-skills:
    ./core/scripts/check-refs.sh

# Install the tracked git hooks for this checkout.
hooks:
    .githooks/install

# Reject dependencies whose licenses are outside the permissive allow-list.
test-licenses:
    uv run --locked python app/tests/check_licenses.py

# Build the portable PEX and verify its installed skill tree.
test-pex:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    uv run --locked python {{ PEX_BUILDER }} "$tmp/pex"
    "$tmp/pex/varde.pex" --version
    skills="$tmp/skills"
    home="$tmp/home"
    env HOME="$home" XDG_CONFIG_HOME="$home/.config" \
        VARDE_CONFIG_DIR="$home/.config/varde" "$tmp/pex/varde.pex" setup sync \
        --skills-dir "$skills" --agents-dir "$tmp/agents" --harnesses none \
        --link-mode copy --preset full --json
    test "$(find "$skills" -mindepth 1 -maxdepth 1 -type d -name 'varde-*' | wc -l | tr -d ' ')" -eq 18
    test -x "$skills/varde-swarm/scripts/select-plans.py"
