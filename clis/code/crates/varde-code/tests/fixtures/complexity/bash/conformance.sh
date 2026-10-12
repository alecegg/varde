#!/usr/bin/env bash

if_else_if_else() {
  if [[ $1 == a ]]; then
    echo a
  elif [[ $1 == b ]]; then
    echo b
  else
    echo other
  fi
}

else_if_body_nesting() {
  if [[ $1 ]]; then
    echo first
  elif [[ $2 ]]; then
    if [[ $3 ]]; then echo nested; fi
  fi
}

else_body_nesting() {
  if [[ $1 ]]; then
    echo first
  else
    if [[ $2 ]]; then echo nested; fi
  fi
}

nested_if() {
  if [[ $1 ]]; then
    if [[ $2 ]]; then
      echo yes
    fi
  fi
}

loops() {
  for x in a b; do
    while [[ $x ]]; do
      until [[ $x == done ]]; do
        if [[ $x ]]; then echo x; fi
        break
      done
      break
    done
  done
  select choice in a b; do break; done
  for ((i=0; i<2; i++)); do echo "$i"; done
}

switch_once() {
  case "$1" in
    a) echo a ;;
    b) echo b ;;
    *) echo other ;;
  esac
}

ternary() {
  (( result = $1 ? $2 : $3 ))
}

early_return_zero() {
  if [[ ! $1 ]]; then return 0; fi
  echo value
}

logical_run_same() {
  [[ $1 && $2 && $3 ]]
}

logical_run_mixed() {
  test -n "$1" && test -n "$2" || test -n "$3"
}

logical_negated_run() {
  [[ $1 && ! ( $2 && $3 ) ]]
}

named_nested_function() {
  inner() {
    if [[ $1 ]]; then echo yes; fi
  }
  inner "$1"
}

condition_nesting() {
  if (( $1 ? $2 : $3 )); then echo yes; fi
}

multi_level_break() {
  for x in a b; do
    while [[ $x ]]; do
      break 2
    done
  done
  for y in a b; do continue 2; done
}

labeled_jumps() {
  for x in a; do
    while [[ $x ]]; do break 2; done
  done
}

recursion_direct() {
  if (( $1 > 0 )); then recursion_direct "$(( $1 - 1 ))"; fi
}

recursion_two_calls() {
  if (( $1 > 1 )); then
    recursion_two_calls "$(( $1 - 1 ))"
    recursion_two_calls "$(( $1 - 2 ))"
  fi
}

recursion_same_file_cycle_a() {
  if (( $1 > 0 )); then recursion_same_file_cycle_b "$(( $1 - 1 ))"; fi
}

recursion_same_file_cycle_b() {
  recursion_same_file_cycle_a "$1"
}

# This peer is defined in another file; this one-file fixture cannot resolve it.
recursion_cross_file_zero() {
  if (( $1 > 0 )); then recursion_cross_file_peer "$1"; fi
}

spec_example_small() {
  case "$1" in
    1) echo one ;;
    2) echo couple ;;
    3) echo few ;;
    *) echo lots ;;
  esac
}

spec_example_large() {
  for ((i=1; i<=$1; i++)); do
    for ((j=2; j<i; j++)); do
      if (( i % j == 0 )); then
        continue 2
      fi
    done
    (( total += i ))
  done
}
