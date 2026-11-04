def __init__(self, config: Config) -> None:
    self.config = config
    try:
        self.fnpats = config.getini("python_files")
    except ValueError:
        self.fnpats = ["test_*.py", "*_test.py"]
    self.session: Session | None = None
    self._rewritten_names: dict[str, Path] = {}
    self._must_rewrite: set[str] = set()
    # flag to guard against trying to rewrite a pyc file while we are already writing another pyc file,
    # which might result in infinite recursion (#3506)
    self._writing_pyc = False
    self._basenames_to_check_rewrite = {"conftest"}
    self._marked_for_rewrite_cache: dict[str, bool] = {}
    self._session_paths_checked = False
