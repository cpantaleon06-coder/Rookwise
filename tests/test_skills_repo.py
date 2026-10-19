"""The ported skills in skills/ load, match config/skills.json and carry attribution."""

import json
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
    if skill.source_url == "original":
        # Written for Rookwise: the repository's license and holder, no third-party notice.
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        assert license_text.startswith(f"{skill.license} License")
        assert f"Copyright (c) 2026 {skill.copyright_holder}" in license_text
        assert f"skills/{skill_id}/" not in notices
    else:
        assert f"skills/{skill_id}/SKILL.md" in notices
        assert any(skill.license in p.name for p in (ROOT / "licenses").iterdir())
    for role in skill.roles:
        assert skill_id in CONFIG["roles"][role]["skills"]


INCIDENT_SKILLS = {
    "log-reader": "log-reading",
    "metrics-reader": "metrics-reading",
    "deploy-diff-reader": "deploy-diff-reading",
}


@pytest.mark.parametrize(("role", "skill_id"), sorted(INCIDENT_SKILLS.items()))
def test_the_incident_roles_read_on_lightning_with_their_original_skill(role, skill_id):
    spec = CONFIG["roles"][role]
    assert spec["model"] == "nemotron-3.5-lightning" and spec["skills"] == [skill_id]
    assert "level" not in spec  # operator roles
    assert load_skill(skill_id).source_url == "original"
    assert "measured_prompt_tokens" not in CONFIG["skills"][skill_id]  # the loader estimates
    composed = compose_system_prompt(role, "Base.")
    assert composed.token_method == {skill_id: "estimate_chars_div_4"}


@pytest.mark.parametrize("skill_id", sorted(INCIDENT_SKILLS.values()))
def test_the_incident_skills_carry_the_citation_rules_and_nothing_from_the_corpus(skill_id):
    body = load_skill(skill_id).body
    for rule in (
        "one single",
        "verbatim",
        "several citations",
        "Never join",
        "ERROR or WARN",
        "nothing relevant" if skill_id == "log-reading" else "no change relevant",
        "nothing else",
    ):
        assert rule in body, rule
    assert body.rstrip().endswith("Keep the output format the task requires (for example JSON).")
    lowered = body.lower()
    incidents = ROOT / "benchmarks" / "incidents"
    for truth_path in sorted(incidents.glob("*/ground_truth.json")):
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        assert truth["incident_id"].lower() not in lowered
        assert truth["root_cause_category"].replace("_", " ") not in lowered
        assert truth["root_cause_category"] not in lowered
        refs = truth["essential_evidence"] + truth["supporting_evidence"] + truth["decoys"]
        for ref in refs:
            assert ref["quote"].lower() not in lowered


@pytest.mark.parametrize("role", sorted(CONFIG["roles"]))
def test_every_role_composes_within_its_ceilings(role):
    composed = compose_system_prompt(role, "You are a Rookwise operator.")
    assert composed.skill_ids == tuple(CONFIG["roles"][role]["skills"])
