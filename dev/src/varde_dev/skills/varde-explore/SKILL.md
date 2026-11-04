---
name: varde-explore
description: "Use this skill when you want to find what exists in the code and what depends on what, look up past plans and reviews, or compare design options before committing, answered in chat."
recommends: [varde-code, varde-plan, varde-build]
---

# Explore before committing

- Find relevant code and report what exists and what depends on what. Ground answers in files read and cite `path:line`.
- For structure questions and blast radius, load `references/varde-code-cli.md`.
- For options, compare credible alternatives against project constraints and recommend one. State what remains uncertain.
- Search past plans and reviews with `varde search "<query>" --in plans`; it covers only plans and reviews in the repo, so cap output.
- Exploration is read-only: it changes no source and writes no plan or HTML file.
- When the user asks to plan or build, start planning or building in the same turn.
