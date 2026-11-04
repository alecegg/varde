#!/usr/bin/env bash
set -euo pipefail

# Seed the prototype that eval 2's prompt names.
dir=working/prototypes/profile-panel
mkdir -p "$dir"
cat > "$dir/v1.md" <<'MD'
# Profile panel v1

Compact two-column layout: details on the left, actions on the right.

```ui
panel = wireframe(
  title: "Profile panel",
  grid: ["DDDDAA", "DDDDAA"],
  regions: {"D": "Details: Ada Lovelace, ada@example.com", "A": "Actions: Edit profile, Sign out"},
)
```
MD
