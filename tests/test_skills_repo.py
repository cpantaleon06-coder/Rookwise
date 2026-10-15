"""The ported skills in skills/ load, match config/skills.json and carry attribution."""

from pathlib import Path

import pytest

from rookwise.skills import compose_system_prompt, load_config, load_skill

ROOT = Path(__file__).resolve().parents[1]
SKILL_IDS = sorted(p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md"))
CONFIG = load_config()


def test_config_and_folders_name_the_same_skills():
    assert SKILL_IDS == sorted(CONFIG["skills"])


@pytest.mark.parametrize("skill_id", SKILL_IDS)
def test_skill_is_valid_and_attributed(skill_id):
    skill = load_skill(skill_id)
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert f"skills/{skill_id}/SKILL.md" in notices
    assert any(skill.license in p.name for p in (ROOT / "licenses").iterdir())
    for role in skill.roles:
        assert skill_id in CONFIG["roles"][role]["skills"]


@pytest.mark.parametrize("role", sorted(CONFIG["roles"]))
def test_every_role_composes_within_its_ceilings(role):
    composed = compose_system_prompt(role, "You are a Rookwise operator.")
    assert composed.skill_ids == tuple(CONFIG["roles"][role]["skills"])
