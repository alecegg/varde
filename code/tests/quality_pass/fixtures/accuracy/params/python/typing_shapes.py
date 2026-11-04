"""Typing-heavy declaration shapes for the parameter-count audit."""


def convert(value: int | str, *, strict: bool = False):
    del strict
    return value


def merge(
    left: dict[str, int],
    right: dict[str, int],
    *,
    replace: bool = False,
):
    return right if replace else {**left, **right}


def pick(items: list[int], index: int = 0):
    return items[index]


def callback(handler, *args, **kwargs):
    return handler(*args, **kwargs)


def positional(a, b, /, c, *, d):
    return a + b + c + d


def defaults_in_tail(a, b=1, c=2, d=3):
    return a + b + c + d


def star_only(*, a, b, c):
    return a + b + c


def plain():
    return None


def unpack(pair, /, *, scale=1):
    first, second = pair
    return (first + second) * scale
