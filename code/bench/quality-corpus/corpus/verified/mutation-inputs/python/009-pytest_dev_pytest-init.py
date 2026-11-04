def __init__(self, obj: object = None) -> None:
    if not obj:
        self.lines: list[str] = []
        self.raw_lines: list[str] = []
        return
    match obj:
        case Source():
            self.lines = obj.lines
            self.raw_lines = obj.raw_lines
        case tuple() | list():
            self.lines = deindent(x.rstrip("\n") for x in obj)
            self.raw_lines = [x.rstrip("\n") for x in obj]
        case str():
            self.lines = deindent(obj.split("\n"))
            self.raw_lines = obj.split("\n")
        case _:
            try:
                rawcode = getrawcode(obj)
                src = inspect.getsource(rawcode)
            except TypeError:
                src = inspect.getsource(obj)  # type: ignore[arg-type]
            self.lines = deindent(src.split("\n"))
            self.raw_lines = src.split("\n")
