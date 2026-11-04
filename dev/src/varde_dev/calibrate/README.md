# Calibration tool

Run the first setup step from the repository root:

```sh
uv sync --locked --all-packages
```

Run the tool with `uv run python -m varde_dev.calibrate <command>`. Its
commands are being added incrementally. Run the calibration tool tests
explicitly with `uv run pytest dev/tests/calibrate`; `just test` skips `dev/`.
