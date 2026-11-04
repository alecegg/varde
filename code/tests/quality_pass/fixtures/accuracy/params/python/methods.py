"""Method and nested-function shapes for the parameter-count audit."""


class Store:
    def __init__(self, root):
        self.root = root
        self.entries = {}

    def get(self, key):
        return self.entries.get(key)

    def put(self, key, value):
        self.entries[key] = value

    def items(self):
        return list(self.entries.items())

    @classmethod
    def from_config(cls, config):
        return cls(config["root"])

    @staticmethod
    def parse(raw):
        return raw.strip()


def outer(x):
    def helper(y, z):
        return y + z

    return helper(x, x)


class Widget:
    def __init__(self, name="widget", *parts, **flags):
        del parts, flags
        self.name = name
