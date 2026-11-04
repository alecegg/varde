import pytest
from varde.manifest import Manifest, install_closure, parse_manifest


def test_parse_manifest_reads_name_and_requires() -> None:
    assert parse_manifest('name = "toz"\nrequires = ["core"]\n') == Manifest(
        "toz", ("core",)
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("requires = []", "manifest name must be a non-empty string"),
        ('name = "x"\nother = 1', "unknown manifest keys: other"),
        (
            'name = "x"\nrequires = "core"',
            "manifest requires must be a list of strings",
        ),
    ],
)
def test_parse_manifest_rejects_malformed_data(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_manifest(text)


def test_install_closure_is_transitive_and_sorted() -> None:
    manifests = {
        "workflow": Manifest("workflow", ("knowledge", "code", "toz", "learn", "dev")),
        "knowledge": Manifest("knowledge", ()),
        "code": Manifest("code", ()),
        "toz": Manifest("toz", ()),
        "learn": Manifest("learn", ()),
        "dev": Manifest("dev", ()),
    }
    assert install_closure("workflow", manifests) == (
        "code",
        "dev",
        "knowledge",
        "learn",
        "toz",
        "workflow",
    )


def test_install_closure_reports_unknown_modules_and_cycles() -> None:
    with pytest.raises(
        ValueError, match="module workflow requires unknown module missing"
    ):
        install_closure("workflow", {"workflow": Manifest("workflow", ("missing",))})
    with pytest.raises(ValueError, match="dependency cycle: a -> b -> a"):
        install_closure("a", {"a": Manifest("a", ("b",)), "b": Manifest("b", ("a",))})
