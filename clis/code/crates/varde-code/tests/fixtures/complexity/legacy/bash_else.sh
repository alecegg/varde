#!/usr/bin/env bash

choose() {
  if [[ "$1" == yes ]]; then
    echo yes
  else
    echo no
  fi
}
