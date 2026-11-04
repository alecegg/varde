---
topic: varde-customize/profile-deploy
version: 1
summary: Toz profile steps 4-5 and report follow-up, part 2 of 2, get authorization before acting
---

## 4. Install at the intended scope

- **Project (default):** the target repository's `.varde/toz-profiles.toml`.
- **User:** `<root>/toz/profiles.toml`, where root is `VARDE_CONFIG_DIR`, else
  `XDG_CONFIG_HOME/varde`, else `~/.config/varde`.

## 5. Verify deployment

- **Loaded:** in the target project, run `varde setup profiles list --json` and
  `varde setup profiles test --json`; check each profile's id, file, scope,
  script presence, cases, and diagnostics.
- **Trusted:** project scripts run only when the user's profiles file lists the
  canonical root in top-level `trusted_projects = ["/absolute/project", ...]`.
- **Matched:** inspect a representative capture's preview and records.

## When a diagnosis report started this

- Get authorization before acting on the report's recommendation.
- Compare before/after output size and retrieval effort, and report whether
  critical details survived. Link the originating report and friction item when
  supplied.
