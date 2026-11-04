#!/bin/sh
set -eu

launcher=$1
payload=$2
shift 2
exec "$launcher" "$@" < "$payload"
