def path(self) -> Path | str:
    """Return a path object pointing to source code, or an ``str`` in
    case of ``OSError`` / non-existing file."""
    filename = inspect.getfile(self.raw)
    if not filename:
        return ""
    try:
        p = absolutepath(filename)
        # maybe don't try this checking
        if not p.exists():
            raise OSError("path check failed.")
        return p
    except OSError:
        # XXX maybe try harder like the weird logic
        # in the standard lib [linecache.updatecache] does?
        return filename
