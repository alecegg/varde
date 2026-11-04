"""Bundle bookkeeping predicates shared by tree walkers."""


def is_artifact_dir(name: str) -> bool:
    return name in {"target", "node_modules"}


def is_reserved(name: str) -> bool:
    return name in {"index.md", "log.md", "README.md"}
