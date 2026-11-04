#!/bin/sh
# macOS-only: size-limited lossy JPEG preview; this cap is not a Read limit.
# usage: shot.sh URL OUT.jpg [WIDTH=390] [HEIGHT=1000]
set -eu
[ "$#" -ge 2 ] || { echo "usage: shot.sh URL OUT.jpg [WIDTH] [HEIGHT]" >&2; exit 2; }
url=$1; out=$2; width=${3:-390}; height=${4:-1000}
limit=49152
cache=${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}
bin=$(find "$cache" -maxdepth 4 -type f -name chrome-headless-shell -path '*/chromium_headless_shell-*/*' | sort -V | tail -1)
[ -n "$bin" ] || { echo "cached chrome-headless-shell not found under $cache" >&2; exit 1; }
tmp=$(mktemp -d "${TMPDIR:-/tmp}/shot.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
# --single-process --no-zygote avoids the Mach port rendezvous the Seatbelt sandbox denies.
"$bin" --no-sandbox --single-process --no-zygote --disable-gpu --hide-scrollbars \
  --window-size="$width,$height" --screenshot="$tmp/raw.png" "$url" >/dev/null 2>"$tmp/err" || true
if [ ! -s "$tmp/raw.png" ]; then
  tail -n 20 "$tmp/err" >&2
  echo "capture failed for $url" >&2
  exit 1
fi
for q in 60 45 30 20 10; do
  sips -s format jpeg -s formatOptions "$q" "$tmp/raw.png" --out "$out" >/dev/null
  [ "$(stat -f %z "$out")" -le "$limit" ] && exit 0
done
rm -f "$out"
echo "$out is still over $limit bytes at quality 10; use a shorter HEIGHT or smaller WIDTH" >&2
exit 1
