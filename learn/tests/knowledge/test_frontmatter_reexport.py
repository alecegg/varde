from varde_core.frontmatter import FrontmatterError, parse, serialize
from varde_core.yamlio import YamlSyntaxError, dump_yaml, load_yaml
from varde_learn.knowledge import formats, frontmatter


def test_frontmatter_public_names_reexport_core_objects() -> None:
    assert frontmatter.FrontmatterError is FrontmatterError
    assert frontmatter.parse is parse
    assert frontmatter.serialize is serialize


def test_yaml_public_names_reexport_core_objects() -> None:
    assert formats.YamlSyntaxError is YamlSyntaxError
    assert formats.dump_yaml is dump_yaml
    assert formats.load_yaml is load_yaml
