"""Decision file types shared by the runner and workflow watcher."""

DECISION_FILE_TYPES = frozenset(
    {"approval", "choice", "decision", "design", "design_decision", "question"}
)
