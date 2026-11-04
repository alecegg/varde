def escape_rst(text: str) -> str:
    """Rudimentary attempt to escape special RST characters to appear as
    plain text."""
    text = (
        text.replace("*", "\\*")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("`", "\\`")
    )
    text = re.sub(r"_\b", "", text)
    return text
