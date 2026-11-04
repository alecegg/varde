# Second seeded samples (tuning route R2, 2026-10-30)

One extra sample per language, landed hash-pinned with `tools/land_sample.py` under `code/src/varde_code/quality_score/samples/`. Each has its own gaming variants and size control in `seeded/<language>/<sample id>/` (the tuner reads that directory when it exists, else `seeded/<language>/`).

| Language | Sample id | Seed domain (fixed before the run) | Versions |
| --- | --- | --- | --- |
| csharp | s38b663cf | event ticket booking | original, 5 judges, smoothed; tiny, namematched, padded, monolith, sizematched |
| csharp | sba591f1b | parking garage fees (route R2b, third C# sample) | original, 5 judges, smoothed; tiny, namematched, padded, monolith, sizematched |
| csharp | s7380467d | parcel shipping quotes (route R2c, fourth C# sample) | same |
| python | sd4f3e756 | library loan fines | same |
| typescript | s077023b7 | subscription invoicing | same |

Authoring: codex gpt-6-luna (medium, the user's subscription client), one call each for the author, five style judges and the top judge, using the 2026-10-22 prompts with only the domain line changed; one further call writes the five gaming variants from a fixed brief. Every version passes its `behaviour_test` (smoothed and all gaming variants rechecked independently). Nothing was edited after the first score. Prompts, logs, held-out results and seeds are in the tuning plan's `notes/t9/`.

Measured sizes (`item_targets.py`, tokens/functions): the layered band checker was written for the first samples, so every smoothed target already sits outside the small-item bands (status `drift`).

| Sample | sensible | monolith | tiny | padded | sizematched | namematched |
| --- | --- | --- | --- | --- | --- | --- |
| s38b663cf | 865/14 | 969/4 | 1324/42 | 1075/24 | 903/4 | 1324/42 |
| sd4f3e756 | 975/13 | 1316/2 | 1311/40 | 1292/20 | 1022/3 | 1370/40 |
| s077023b7 | 895/8 | 929/2 | 1690/50 | 1190/16 | 812/4 | 1732/50 |

No mutation spec was written for these samples.
