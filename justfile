# Cross-module test entry point. Each recipe only enters a module and runs its own test command.

default:
    @just --list

# Run every suite and report all failing suites.
test:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=()
    for suite in test-skills test-agents test-root test-licenses test-clis test-pi; do
      "{{just_executable()}}" "$suite" || failed+=("$suite")
    done
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "FAIL: ${failed[*]}" >&2
      exit 1
    fi
    echo "all suites passed"

test-skills:
    cd skills && tests/benchmark-foundation.sh && tests/route-budgets.sh --check

test-agents:
    agents/tests/run-all.sh

test-root:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=()
    for test_script in tests/*.sh; do
      bash "$test_script" || failed+=("$test_script")
    done
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "FAIL: ${failed[*]}" >&2
      exit 1
    fi

# The release license gate: fails on a dependency outside the permissive allow-list.
test-licenses:
    cargo fetch --locked --manifest-path clis/Cargo.toml
    python3 clis/code/scripts/gen-third-party-licenses.py

test-cli module:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{module}}" in
      code) packages=(-p varde-code) ;;
      workflow) packages=(-p varde-workflow-core -p varde-workflow) ;;
      toz) packages=(-p varde-toz-core -p varde-toz) ;;
      learn) packages=(-p varde-learn-core -p varde-learn) ;;
      doc) packages=(-p varde-doc) ;;
      shared) packages=(-p varde-core -p varde-contracts) ;;
      *) echo "unknown module: {{module}}" >&2; exit 2 ;;
    esac
    cd clis
    cargo test --locked "${packages[@]}"
    if [ "{{module}}" = shared ]; then
      # The app crate's own tests and the boundary tests, run by no module above.
      cargo test --locked -p varde --lib --test no_named_spawn --test dependency_rules --test sync_suite --test setup_suite --test misc_suite
      exit
    fi
    # Binary-spawning tests live in the app crate, one suite binary per module.
    if [ "{{module}}" != doc ]; then
      cargo test --locked -p varde --test "{{module}}_suite"
    fi

test-clis:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=()
    for module in shared code workflow toz learn doc; do
      "{{just_executable()}}" test-cli "$module" || failed+=("$module")
    done
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "FAIL: ${failed[*]}" >&2
      exit 1
    fi

test-pi:
    node --test clis/varde/assets/hooks/tests/varde.test.mjs
