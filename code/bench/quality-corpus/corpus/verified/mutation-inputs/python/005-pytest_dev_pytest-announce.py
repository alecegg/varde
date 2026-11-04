def announce(version: str, template_name: str, doc_version: str) -> None:
    """Generates a new release announcement entry in the docs."""
    # Get our list of authors and co-authors.
    stdout = check_output(["git", "describe", "--abbrev=0", "--tags"], encoding="UTF-8")
    last_version = stdout.strip()
    rev_range = f"{last_version}..HEAD"

    authors = check_output(
        ["git", "log", rev_range, "--format=%aN"], encoding="UTF-8"
    ).splitlines()

    co_authors_output = check_output(
        ["git", "log", rev_range, "--format=%(trailers:key=Co-authored-by) "],
        encoding="UTF-8",
    )
    co_authors: list[str] = []
    for co_author_line in co_authors_output.splitlines():
        if m := re.search(r"Co-authored-by: (.+?)<", co_author_line):
            co_authors.append(m.group(1).strip())

    contributors = {
        name
        for name in authors + co_authors
        if not name.endswith("[bot]") and name != "pytest bot"
    }

    template_text = (
        Path(__file__).parent.joinpath(template_name).read_text(encoding="UTF-8")
    )

    contributors_text = "\n".join(f"* {name}" for name in sorted(contributors)) + "\n"
    text = template_text.format(
        version=version, contributors=contributors_text, doc_version=doc_version
    )

    target = Path(__file__).parent.joinpath(f"../doc/en/announce/release-{version}.rst")
    target.write_text(text, encoding="UTF-8")
    print(f"{Fore.CYAN}[generate.announce] {Fore.RESET}Generated {target.name}")

    # Update index with the new release entry
    index_path = Path(__file__).parent.joinpath("../doc/en/announce/index.rst")
    lines = index_path.read_text(encoding="UTF-8").splitlines()
    indent = "   "
    for index, line in enumerate(lines):
        if line.startswith(f"{indent}release-"):
            new_line = indent + target.stem
            if line != new_line:
                lines.insert(index, new_line)
                index_path.write_text("\n".join(lines) + "\n", encoding="UTF-8")
                print(
                    f"{Fore.CYAN}[generate.announce] {Fore.RESET}Updated {index_path.name}"
                )
            else:
                print(
                    f"{Fore.CYAN}[generate.announce] {Fore.RESET}Skip {index_path.name} (already contains release)"
                )
            break

    check_call(["git", "add", str(target)])
