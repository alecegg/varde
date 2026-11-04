---
name: varde-x
description: Fixture skill for reset tests.
---

# Fixture skill

Do the fixture job.

## Outcomes

- The job is done and reported.

## Procedure

First read every input file. Then list what changed in each of them and
write one summary line per file, in the order the files were read.

## Edge cases

When an input file is binary, skip it and note the skip in the summary so the
reader knows it was not read.

## Validation

Check that the summary names every input file.
