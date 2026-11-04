import json
from pathlib import Path

from varde_design.survey import (
    build_survey,
    files_to_read,
    find_design_docs,
    is_page,
    page_score,
    project_root,
)
from varde_design.survey_report import MAX_BYTES, render_survey, survey_data
from varde_design.survey_walk import read_texts, walk_project

TOKENS = ":root { --bg: #fff; --fg: #111; --space-4: 4px; }"
PKG = json.dumps({"dependencies": {"react": "18", "styled-components": "6"}})


def test_empty_project_reports_absence_explicitly() -> None:
    survey = build_survey([], {})
    text = render_survey(survey)
    assert "tokens: no tokens found" in text
    assert "components: no component library" in text
    assert "pages: none found" in text
    assert "design docs: none" in text
    assert survey.styling == "none" and survey.frameworks == []


def test_tokens_from_css_json_and_theme_config() -> None:
    paths = ["src/a.css", "src/b.css", "tokens.json", "tailwind.config.js"]
    texts = {
        "src/a.css": TOKENS,
        "src/b.css": "p { color: red }",
        "tailwind.config.js": "module.exports = { theme: {} }",
    }
    survey = build_survey(paths, texts)
    assert survey.token_sheets == [("src/a.css", 3)]
    assert survey.token_total == 3
    assert survey.token_json == ["tokens.json"]
    assert survey.theme_configs == ["tailwind.config.js"]
    assert survey.styling.startswith("utility classes")


def test_theme_config_without_theme_is_not_reported() -> None:
    survey = build_survey(["tailwind.config.js"], {"tailwind.config.js": "x = 1"})
    assert survey.theme_configs == []


def test_framework_and_styling_from_package_json() -> None:
    survey = build_survey(["package.json", "App.vue"], {"package.json": PKG})
    assert survey.frameworks == ["react", "vue"]
    assert survey.styling == "css-in-js"


def test_malformed_package_json_is_ignored() -> None:
    survey = build_survey(["package.json"], {"package.json": "{not json"})
    assert survey.frameworks == []
    survey = build_survey(["package.json"], {"package.json": "[1, 2]"})
    assert survey.frameworks == []


def test_css_modules_and_plain_css_styling() -> None:
    assert build_survey(["a.module.css"], {"a.module.css": ""}).styling == "css modules"
    assert build_survey(["index.html"], {}).styling == "plain css"


def test_components_listed_and_not_counted_as_pages() -> None:
    paths = ["src/components/Button.tsx", "src/components/Card.tsx", "src/app/page.tsx"]
    survey = build_survey(paths, dict.fromkeys(paths, ""))
    assert survey.components == ["Button", "Card"]
    assert survey.component_dirs == ["src/components"]
    assert [p for p, _ in survey.pages] == ["src/app/page.tsx"]
    assert not is_page("src/components/Button.tsx")


def test_pages_ranked_by_token_use_and_state_coverage() -> None:
    rich = "color: var(--fg); background: var(--bg); a:hover{} :focus{} .error{}"
    texts = {"a.html": "<p>plain</p>", "b.html": rich, "c.html": "var(--x)"}
    survey = build_survey(list(texts), texts)
    assert [p for p, _ in survey.pages] == ["b.html", "c.html", "a.html"]
    assert page_score(rich) == 2 + 3 * 3
    assert page_score("") == 0


def test_design_docs_in_search_order() -> None:
    paths = [
        "docs/DESIGN.md",
        "DESIGN.md",
        ".agents/context/design.md",
        "DESIGN.json",
        ".impeccable/design.json",
        "docs/Style Guide.md",
        "README.md",
    ]
    assert find_design_docs(paths) == [
        "DESIGN.md",
        ".agents/context/design.md",
        "docs/DESIGN.md",
        ".impeccable/design.json",
        "DESIGN.json",
        "docs/Style Guide.md",
    ]
    assert find_design_docs(["README.md"]) == []


def test_project_root_stops_at_nearest_marker() -> None:
    marked = {"", "pkgs/web"}
    assert project_root("pkgs/web/src", marked) == "pkgs/web"
    assert project_root("pkgs/other", marked) == ""
    assert project_root("x/y", set()) == "x/y"
    assert project_root("", set()) == ""


def test_files_to_read_respects_size_cap() -> None:
    paths = ["a.css", "big.css", "p.html", "package.json", "notes.txt"]
    sizes = {"a.css": 10, "big.css": 600 * 1024, "p.html": 5, "package.json": 1}
    assert files_to_read(paths, sizes) == ["a.css", "package.json", "p.html"]


def test_render_is_capped_and_data_is_json_ready() -> None:
    paths = [f"s/{i}.css" for i in range(300)]
    texts = {p: f":root {{ --a-{i}: 1px; }}" for i, p in enumerate(paths)}
    survey = build_survey(paths, texts, truncated=True)
    text = render_survey(survey)
    assert len(text.encode()) <= MAX_BYTES
    assert "truncated: walk stopped" in text
    assert "(+292 more)" in text
    json.dumps(survey_data(survey))


def test_walk_skips_build_dirs_and_reads_texts(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.css").write_text(TOKENS)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.css").write_text(TOKENS)
    walk = walk_project(tmp_path)
    assert walk.paths == ["src/a.css"] and not walk.truncated
    assert walk.sizes["src/a.css"] == len(TOKENS)
    assert read_texts(tmp_path, ["src/a.css", "gone.css"]) == {"src/a.css": TOKENS}


def test_walk_truncates_at_file_cap(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"{i}.css").write_text("")
    walk = walk_project(tmp_path, max_files=3)
    assert len(walk.paths) == 3 and walk.truncated
    assert walk_project(tmp_path, max_files=3, max_seconds=-1).truncated
