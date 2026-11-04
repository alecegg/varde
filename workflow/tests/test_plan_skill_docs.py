from pathlib import Path

SKILL = Path(__file__).parents[1] / "src/varde_workflow/skills/varde-plan"


def test_plan_label_guidance_states_all_validator_rules() -> None:
    for relative in ("assets/PLAN-TEMPLATE.md", "references/plan.md"):
        text = (SKILL / relative).read_text(encoding="utf-8").casefold()
        assert "3-5 words" in text or "3 to 5 words" in text
        assert "36 characters" in text
        assert "date" in text or "dates" in text
        assert "version" in text
        assert "plan id" in text or "ids" in text
        assert "unique among open plans" in text
