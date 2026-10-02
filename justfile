# Cross-module test entry point. Each recipe only enters a module and runs its own test command.

default:
    @just --list

# Run every suite and report all failing suites.
test:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=()
    for suite in test-skills test-agents test-root test-clis test-pi; do
      "{{just_executable()}}" "$suite" || failed+=("$suite")
    done
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "FAIL: ${failed[*]}" >&2
      exit 1
    fi
    echo "all suites passed"

test-skills:
    cd skills && tests/benchmark-foundation.sh

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

test-cli module:
    cd clis/{{module}} && cargo test --workspace --locked

test-clis:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=()
    for module in code workflow toz learn; do
      "{{just_executable()}}" test-cli "$module" || failed+=("$module")
    done
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "FAIL: ${failed[*]}" >&2
      exit 1
    fi

test-pi:
    node --test clis/toz/harness/pi/tests/varde-toz.test.mjs
