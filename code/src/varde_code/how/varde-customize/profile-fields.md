---
topic: varde-customize/profile-fields
version: 1
summary: Toz profile fields and the install locations
---

- `id`, plus exactly one selector: `match = { command = "<glob>" }` or
  `{ source = "<glob>" }`.
- Sections (optional): `sections = { heading = "<regex>" }`; use `start`
  (regex) or `jsonl_key` (field) instead of `heading`, exactly one.
- Top-level `merge_small` (bool, default true).
- Preview (optional): `preview = { kind = "toc" | "head", items_per_section = <n>,
  item = "<regex>" }`; only `kind` is required.
- `script` (optional): QuickJS record extractor, required for `expect_records`;
  request topic `profile-scripts` before writing one; project scripts also need
  the trust entry.

Install locations: project `.varde/toz-profiles.toml` (default); user
`<root>/toz/profiles.toml`, root being `VARDE_CONFIG_DIR`, else
`XDG_CONFIG_HOME/varde`, else `~/.config/varde`.
