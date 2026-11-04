from pathlib import Path

from varde_learn.docs import how_cmd

TOPIC = "---\ntopic: t\nversion: 1\nsummary: s\n---\n{body}\n"


def _write(skill_dir: Path, step: str, body: str) -> None:
    (skill_dir / "how").mkdir(parents=True, exist_ok=True)
    (skill_dir / "how" / f"{step}.md").write_text(TOPIC.format(body=body))


def _package_topics(tmp_path: Path):
    pkg = tmp_path / "pkg"
    skill = pkg / "varde-x"
    skill.mkdir(parents=True)
    for step in ("a", "b"):
        (skill / f"{step}.md").write_text(TOPIC.format(body=f"package {step}"))
    return how_cmd.load_topics([pkg])


def test_installed_topics_replace_package_topics(tmp_path):
    installed = tmp_path / "sync" / "varde-x"
    _write(installed, "a", "edited a")
    topics = how_cmd.all_topics([], [], how_cmd.load_installed_topics([installed]))
    assert topics["varde-x"]["a"].body == "edited a"
    assert set(topics["varde-x"]) == {"a"}


def test_deleted_local_step_stays_deleted(tmp_path):
    package = _package_topics(tmp_path)
    installed = tmp_path / "sync" / "varde-x"
    _write(installed, "a", "edited a")
    merged = {**package, **how_cmd.load_installed_topics([installed])}
    assert "b" not in merged["varde-x"]


def test_skill_without_installed_topics_falls_back(tmp_path):
    installed = tmp_path / "sync" / "varde-x"
    installed.mkdir(parents=True)
    assert how_cmd.load_installed_topics([installed]) == {}
    (installed / "how").mkdir()
    assert how_cmd.load_installed_topics([installed]) == {}
