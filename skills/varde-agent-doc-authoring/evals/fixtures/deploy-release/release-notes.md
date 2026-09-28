# deploy-cli release task notes

Completed workflow for publishing a service release:

1. Run `deploy-cli validate-manifest` to check the manifest's environment names.
2. Run `deploy-cli push` to publish the validated manifest and release artifact.
3. Run `deploy-cli status` to confirm the release completed.

Correction from the completed task: running `push` before `validate-manifest`
can silently mismatch environment names. Keep validation before push and verify
the release status afterward.
