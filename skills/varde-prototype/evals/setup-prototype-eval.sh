#!/usr/bin/env bash
set -euo pipefail

# Seed the prototype that eval 2's prompt names.
dir=memory-bank/working/prototypes/profile-panel
mkdir -p "$dir"
cat > "$dir/v1.html" <<'HTML'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Profile panel v1</title>
<style>.panel { display: grid; grid-template-columns: 2fr 1fr; gap: 1rem; }</style>
</head>
<body>
<main class="panel">
  <section aria-label="Details"><h1>Ada Lovelace</h1><p>ada@example.com</p></section>
  <section aria-label="Actions"><button type="button">Edit profile</button> <button type="button">Sign out</button></section>
</main>
</body>
</html>
HTML
