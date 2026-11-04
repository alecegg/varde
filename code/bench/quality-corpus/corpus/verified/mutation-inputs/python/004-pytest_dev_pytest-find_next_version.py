def find_next_version(
    base_branch: str, is_major: bool, is_feature_release: bool, prerelease: str
) -> str:
    output = check_output(["git", "tag"], encoding="UTF-8")
    valid_versions = []
    for v in output.splitlines():
        m = re.match(r"\d.\d.\d+$", v.strip())
        if m:
            valid_versions.append(tuple(int(x) for x in v.split(".")))

    valid_versions.sort()
    last_version = valid_versions[-1]

    if is_major:
        return f"{last_version[0] + 1}.0.0{prerelease}"
    elif is_feature_release:
        return f"{last_version[0]}.{last_version[1] + 1}.0{prerelease}"
    else:
        return f"{last_version[0]}.{last_version[1]}.{last_version[2] + 1}{prerelease}"
