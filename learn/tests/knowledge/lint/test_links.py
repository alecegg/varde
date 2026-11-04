from varde_learn.knowledge.lint.links import extract_links


def test_extracts_internal_links_and_ignores_code_images_and_external_targets() -> None:
    body = """Inline ` [x](inline.md) `
```md
[x](fenced.md)
```
![image](image.png) [ok](<nested/file.md#part>) [web](https://example.test)
"""
    assert extract_links(body) == ["nested/file.md"]


def test_fence_closer_with_trailing_text_does_not_close_fence() -> None:
    assert extract_links("```\n``` stray\n[masked](bad.md)\n```\n") == []


def test_unclosed_inline_code_only_masks_its_line() -> None:
    assert extract_links("`[masked](bad.md)\n[real](good.md)\n") == ["good.md"]
