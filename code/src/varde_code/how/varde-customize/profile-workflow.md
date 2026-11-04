---
topic: varde-customize/profile-workflow
version: 1
summary: Toz profile steps 1-3, part 1 of 2, fixtures and tests, authorization gate in profile-deploy
---

## 1. Get representative output

1. Establish the command or source to match and the desired preview or records,
   from the request or a capture.
2. Build bounded, redacted fixtures that keep critical errors and context;
   disclose missing evidence instead of copying a full session.

Prefer declarative sections and previews; before writing a script, request
topic `profile-scripts`.

## 2. Inspect active profiles

Run `varde setup profiles list --json` in the target project. Profiles merge by
`id` (project beats user beats built-in); reuse an id only for an intentional
override.

## 3. Draft and test with fixtures

1. Write cases for success, failure, and no-match, asserting preview text and
   records (an empty records array for an extraction negative).
2. Run `varde setup profiles test --file <file> --json`; check that the intended
   cases appear and pass.
