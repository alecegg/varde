#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $(basename "$0") <auto|inline|fresh|parallel> <positive-task-count|task-manifest>" >&2
}

if [ "$#" -ne 2 ]; then
  usage
  exit 2
fi

requested="$1"

if [ -f "$2" ]; then
  manifest="$2"
  case "$requested" in
    inline|fresh)
      printf '%s\n' "$requested"
      ;;
    auto|parallel)
      resolver="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-execution-wave.py"
      exec python3 "$resolver" "$manifest" --strategy "$requested"
      ;;
    *)
      usage
      exit 2
      ;;
  esac
  exit 0
fi

task_count="$2"

case "$task_count" in
  ''|*[!0-9]*)
    usage
    exit 2
    ;;
esac

if [ "$task_count" -lt 1 ]; then
  usage
  exit 2
fi

case "$requested" in
  inline|fresh)
    printf '%s\n' "$requested"
    ;;
  auto)
    if [ "$task_count" -eq 1 ]; then
      printf '%s\n' inline
    else
      printf '%s\n' fresh
    fi
    ;;
  parallel)
    echo "parallel requires a task manifest" >&2
    exit 2
    ;;
  *)
    usage
    exit 2
    ;;
esac
