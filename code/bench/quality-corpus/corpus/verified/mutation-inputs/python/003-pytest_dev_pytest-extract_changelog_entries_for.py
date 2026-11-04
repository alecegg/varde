def extract_changelog_entries_for(version: str) -> str:
    p = Path(__file__).parent.parent / "doc/en/changelog.rst"
    changelog_lines = p.read_text(encoding="UTF-8").splitlines()

    title_regex = re.compile(r"pytest (\d\.\d+\.\d+\w*) \(\d{4}-\d{2}-\d{2}\)")
    consuming_version = False
    version_lines = []
    for line in changelog_lines:
        m = title_regex.match(line)
        if m:
            # Found the version we want: start to consume lines until we find the next version title.
            if m.group(1) == version:
                consuming_version = True
            # Found a new version title while parsing the version we want: break out.
            elif consuming_version:
                break
        if consuming_version:
            version_lines.append(line)

    return "\n".join(version_lines)
