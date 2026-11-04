import pytest
from varde_learn.knowledge.lint.base import BaseLintError, lint_base


def test_lint_base_accepts_valid_frontmatter_without_type() -> None:
    assert lint_base(b"---\ntitle: sample\n---\nBody\n", "my-concept") is None


@pytest.mark.parametrize("slug", ["Not_Kebab", "../../outside", "bad//slug"])
def test_lint_base_rejects_invalid_slug(slug: str) -> None:
    with pytest.raises(BaseLintError) as error:
        lint_base(b"---\ntitle: sample\n---\n", slug)
    assert error.value.kind == "invalid_slug"


def test_lint_base_rejects_invalid_frontmatter() -> None:
    with pytest.raises(BaseLintError) as error:
        lint_base(b"---\n- list\n---\n", "valid")
    assert error.value.kind == "frontmatter"
