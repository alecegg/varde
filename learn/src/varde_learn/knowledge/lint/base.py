"""Structural frontmatter and slug checks for markdown documents."""

from varde_learn.knowledge.crud import validate_slug
from varde_learn.knowledge.frontmatter import FrontmatterError, parse


class BaseLintError(ValueError):
    """A frontmatter or slug validation failure."""

    def __init__(self, kind: str, message: str, *, slug: str | None = None) -> None:
        self.kind = kind
        self.slug = slug
        super().__init__(message)


def lint_base(data: bytes, slug: str) -> None:
    """Require mapping frontmatter and a safe kebab-case slug."""
    try:
        parse(data)
    except FrontmatterError as exc:
        raise BaseLintError("frontmatter", f"frontmatter check failed: {exc}") from exc
    if not validate_slug(slug):
        raise BaseLintError(
            "invalid_slug",
            f"invalid slug `{slug}`: must be kebab-case, e.g. `my-concept`",
            slug=slug,
        )
