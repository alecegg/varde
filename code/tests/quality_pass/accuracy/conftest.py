"""Print the A17-A19 accuracy rates at the end of every pytest session."""

from __future__ import annotations

import accuracy_audit


def pytest_terminal_summary(terminalreporter) -> None:
    lines = accuracy_audit.format_rates()
    if not lines:
        return
    terminalreporter.write_sep("-", "accuracy audit A17-A19")
    for line in lines:
        terminalreporter.write_line(line)
