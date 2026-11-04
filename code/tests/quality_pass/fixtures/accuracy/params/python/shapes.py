"""Declaration shapes for the parameter-count audit (reference counts by hand)."""


def no_args():
    return 0


def one(a):
    return a


def two(a, b):
    return a + b


def with_defaults(a, b=1, c=2):
    return a + b + c


def varargs(a, *args):
    return a + len(args)


def kwargs(a, **options):
    return a + len(options)


def both(a, *args, **options):
    return a + len(args) + len(options)


def keyword_only(a, *, b):
    return a + b


def positional_only(a, /, b):
    return a + b


def mixed(a, b=1, /, c=2, *args, d, **options):
    return a + b + c + len(args) + d + len(options)


def annotated(a: int, b: str = "x") -> None:
    del a, b


def nested_default(a, b=(1, 2), c={}):
    del b, c
    return a
