def spawn(
    spec: str, fmt: str, path: Path, python: str | None
) -> subprocess.Popen[bytes]:
    """Start the dump of one side -- callers start both, then collect."""
    args = [fmt, "plain" if spec == "plain" else "rewrite", str(path)]
    repo = Path(__file__).parent.parent
    # src/ ahead of whatever is installed, so 'worktree' means this checkout.
    env = os.environ | {"PYTHONPATH": str(repo / "src")} if spec == "worktree" else None
    if python is None and spec in ("plain", "worktree"):
        cmd = [sys.executable, "-c", _WORKER, *args]
    else:
        cmd = ["uv", "run"]
        if python is not None:
            cmd += ["--python", python]
        # The worktree needs pytest's dependencies; the other sides need none.
        cmd += ["--project", str(repo)] if spec == "worktree" else ["--no-project"]
        if spec not in ("plain", "worktree"):
            cmd += ["--with", f"pytest=={spec}"]
        cmd += ["--", "python", "-c", _WORKER, *args]
    try:
        return subprocess.Popen(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            f"{exc.filename} not found (uv: https://docs.astral.sh/uv/)"
        ) from None
