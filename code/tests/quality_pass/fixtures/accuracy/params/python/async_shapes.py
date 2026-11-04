"""Async and generator shapes for the parameter-count audit."""


async def fetch(url, *, timeout=1.0):
    del timeout
    return url.encode("utf-8")


async def gather(urls, limit):
    return [url for url in urls[:limit]]


def generate(start, stop, step=1):
    yield from range(start, stop, step)


async def send(value):
    return value


def pipeline(*stages):
    return len(stages)


def configure(**settings):
    return sorted(settings)


def mixed(a, b, *rest, flag=True, **extra):
    del rest, flag, extra
    return a + b


async def inner_await(connection, host, port=8080):
    del connection
    return f"{host}:{port}"
