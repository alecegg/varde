def __call__(self, prefix: str, **kwargs: Any) -> list[str]:
    # Only called on non option completions.
    if os.sep in prefix[1:]:
        prefix_dir = len(os.path.dirname(prefix) + os.sep)
    else:
        prefix_dir = 0
    completion = []
    globbed = []
    if "*" not in prefix and "?" not in prefix:
        # We are on unix, otherwise no bash.
        if not prefix or prefix[-1] == os.sep:
            globbed.extend(glob(prefix + ".*"))
        prefix += "*"
    globbed.extend(glob(prefix))
    for x in sorted(globbed):
        if os.path.isdir(x):
            x += "/"
        # Append stripping the prefix (like bash, not like compgen).
        completion.append(x[prefix_dir:])
    return completion
