"""Skill loader and prompt composer, on skills written to a temporary folder."""

import json
from pathlib import Path

import pytest

from rookwise.skills import (
    SkillError,
    compose_system_prompt,
    load_config,
    load_skill,
    skill_sha256,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"


def _frontmatter(**overrides: str) -> str:
    fields = {
        "name": "minimal-code",
        "description": "Write the smallest code that solves the task.",
        "source_url": "https://example.com/source",
        "upstream_version_or_commit": "v1.0.0",
        "license": "MIT",
        "copyright_holder": "Example Holder",
        "adapted_for": "nemotron",
        "roles": "[coder]",
        "modifications": "Shortened.",
    } | overrides
    lines = [f"{k}: {v}" for k, v in fields.items() if v is not None]
    return "---\n" + "\n".join(lines) + "\n---\n"


def _write(skills_dir: Path, skill_id: str, text: str) -> None:
    (skills_dir / skill_id).mkdir(parents=True, exist_ok=True)
    (skills_dir / skill_id / "SKILL.md").write_text(text, encoding="utf-8")


def _config(skill_max=100, role_max=100, measured=None) -> dict:
    skill = {"max_tokens": skill_max}
    if measured is not None:
        skill["measured_prompt_tokens"] = {"nemotron-3.5-lightning": measured}
    return {
        "skills": {"minimal-code": skill},
        "roles": {
            "coder": {
                "model": "nemotron-3.5-lightning",
                "skills": ["minimal-code"],
                "max_skill_tokens": role_max,
            }
        },
    }


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    _write(tmp_path, "minimal-code", _frontmatter() + "\nUse the standard library first.\n")
    return tmp_path


def test_load_skill_parses_frontmatter_and_body(skills_dir):
    skill = load_skill("minimal-code", skills_dir)
    assert skill.roles == ("coder",)
    assert skill.license == "MIT"
    assert skill.body == "Use the standard library first."


def test_windows_line_endings_are_normalized(tmp_path):
    text = _frontmatter() + "\nUse the standard library first.\n"
    _write(tmp_path, "minimal-code", "")
    (tmp_path / "minimal-code" / "SKILL.md").write_bytes(text.replace("\n", "\r\n").encode())
    assert load_skill("minimal-code", tmp_path).body == "Use the standard library first."


@pytest.mark.parametrize(
    "overrides",
    [
        {"license": None},
        {"license": ""},
        {"adapted_for": "claude"},
        {"name": "other-name"},
        {"roles": "coder"},
        {"roles": "[]"},
        {"extra_field": "x"},
    ],
)
def test_invalid_frontmatter_is_rejected(tmp_path, overrides):
    _write(tmp_path, "minimal-code", _frontmatter(**overrides) + "\nBody.\n")
    with pytest.raises(SkillError):
        load_skill("minimal-code", tmp_path)


def test_empty_body_and_missing_file_are_rejected(tmp_path):
    _write(tmp_path, "minimal-code", _frontmatter() + "\n")
    with pytest.raises(SkillError):
        load_skill("minimal-code", tmp_path)
    with pytest.raises(SkillError):
        load_skill("absent", tmp_path)


def test_compose_is_deterministic_and_returns_skill_ids(skills_dir):
    first = compose_system_prompt(
        "coder", "You are an operator.", config=_config(), skills_dir=skills_dir
    )
    second = compose_system_prompt(
        "coder", "You are an operator.", config=_config(), skills_dir=skills_dir
    )
    assert first == second
    assert first.skill_ids == ("minimal-code",)
    assert first.text.startswith("You are an operator.\n\n## Skill: minimal-code\n\n")
    assert first.token_method == {"minimal-code": "estimate_chars_div_4"}


def test_compose_uses_measured_tokens_when_recorded(skills_dir):
    config = _config(measured=42)
    config["skills"]["minimal-code"]["measured_sha256"] = skill_sha256(
        load_skill("minimal-code", skills_dir)
    )
    composed = compose_system_prompt("coder", "Base.", config=config, skills_dir=skills_dir)
    assert composed.skill_tokens == {"minimal-code": 42}
    assert composed.token_method == {"minimal-code": "measured"}


def test_a_measurement_of_older_skill_text_is_ignored(skills_dir):
    config = _config(measured=42)
    config["skills"]["minimal-code"]["measured_sha256"] = "0" * 64
    composed = compose_system_prompt("coder", "Base.", config=config, skills_dir=skills_dir)
    assert composed.token_method == {"minimal-code": "estimate_chars_div_4"}


@pytest.mark.parametrize("config", [_config(skill_max=1), _config(role_max=1)])
def test_compose_refuses_to_pass_a_ceiling(skills_dir, config):
    with pytest.raises(SkillError):
        compose_system_prompt("coder", "Base.", config=config, skills_dir=skills_dir)


def test_compose_refuses_unknown_roles_and_skills_for_other_roles(skills_dir):
    with pytest.raises(SkillError):
        compose_system_prompt("auditor", "Base.", config=_config(), skills_dir=skills_dir)
    config = _config()
    config["roles"]["reviewer"] = config["roles"].pop("coder")
    with pytest.raises(SkillError):
        compose_system_prompt("reviewer", "Base.", config=config, skills_dir=skills_dir)


def test_repo_config_is_consistent_with_prices():
    config = load_config()
    prices = json.loads((CONFIG / "prices.json").read_text(encoding="utf-8"))
    for role, spec in config["roles"].items():
        assert spec["model"] in prices["per_million_tokens"], role
        assert spec["max_skill_tokens"] > 0, role
    for skill_id, spec in config["skills"].items():
        assert spec["max_tokens"] > 0, skill_id
