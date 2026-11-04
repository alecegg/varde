# Explanation page

- Write markdown prose and `ui` statements (components: `varde learn docs blocks`) at the path the user names, or `<working>/explanations/<YYYY-MM-DD>-<slug>.md` (`<working>` is from `varde setup paths --json`).
- Pass `varde learn check <page>`.
- Export it with `varde learn docs build <page> --out <page without .md>.html`: a static file with no script. Write no HTML by hand.
- The reply reports the exported path.

| Shape | Headings |
|---|---|
| Change | Background, Intuition, Code |
| Area | Background, Intuition, How It Works |
| Options | Options, Tradeoffs, Recommendation |
