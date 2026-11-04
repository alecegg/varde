# Running the design checker on Varde surfaces

Settings live in the repo-root `varde-design.toml` (token sheets, spacing and type scales, 44 px target, 12 px UI text floor). The checker package carries no Varde values.

1. Run from the repository root so `token_files` resolve: `varde design check <url-or-html> --config varde-design.toml`.
2. Both tiers need Playwright (`design` optional extra plus `playwright install chromium`); add `--static-only` for CSS and HTML alone.
3. For a file inside `runner/ui` the checker takes the nearest `package.json` folder as project root, so the sheet paths miss. Pass the sheet explicitly: `--tokens runner/ui/src/style.css`.
4. A `fail` finding (exit 2) is not waivable. Fix it, or mark a `warn` with `design-ignore <id> reason: <24+ characters>`.
5. Known gaps (component names, doc-serve typed blocks, per-path settings) are listed with the calibration counts in the plan notes `t13-gaps.md` and `t13-results.md`.
