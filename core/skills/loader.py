"""Load Nemotron-adapted skills and compose them into a role's system prompt.

A skill is `skills/<id>/SKILL.md`: frontmatter between `---` lines, then the body.
Frontmatter is a strict subset of YAML: one `key: value` per line, and `roles` as a
flow list such as `[coder, reviewer]`. Every field in `FIELDS` is required and no
other field is allowed.

`config/skills.json` maps each role to its model and skill ids and sets a token
ceiling per skill (`max_tokens`) and per role (`max_skill_tokens`, the sum of its
skills). A skill's token count is the measured prompt-token cost on the role's model
when `measured_prompt_tokens` has it, otherwise an ESTIMATE of characters / 4.
Composition is deterministic and refuses to exceed a ceiling.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"
CONFIG_PATH = REPO_ROOT / "config" / "skills.json"

FIELDS = (
    "name",
    "description",
    "source_url",
    "upstream_version_or_commit",
    "license",
    "copyright_holder",
    "adapted_for",
    "roles",
    "modifications",
)

TokenMethod = Literal["measured", "estimate_chars_div_4"]


class SkillError(ValueError):
    """A skill or the skills config is invalid, or composing would pass a ceiling."""


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    source_url: str
    upstream_version_or_commit: str
    license: str
    copyright_holder: str
    adapted_for: str
    roles: tuple[str, ...]
    modifications: str
    body: str

    def render(self) -> str:
        """The block that goes into a system prompt."""
        return f"## Skill: {self.name}\n\n{self.body}"


@dataclass(frozen=True)
class ComposedPrompt:
    text: str
    skill_ids: tuple[str, ...]
    skill_tokens: dict[str, int]
    token_method: dict[str, TokenMethod]


def parse_skill(skill_id: str, text: str) -> Skill:
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise SkillError(f"{skill_id}: SKILL.md must start with a frontmatter line '---'")
    head, sep, body = text[4:].partition("\n---\n")
    if not sep:
        raise SkillError(f"{skill_id}: frontmatter is not closed with '---'")
    fields: dict[str, str] = {}
    for line in head.split("\n"):
        if not line.strip():
            continue
        key, colon, value = line.partition(":")
        if not colon or not key or key != key.strip():
            raise SkillError(f"{skill_id}: bad frontmatter line: {line!r}")
        if key in fields:
            raise SkillError(f"{skill_id}: duplicate frontmatter field {key}")
        fields[key] = value.strip()
    missing = [f for f in FIELDS if not fields.get(f)]
    extra = sorted(set(fields) - set(FIELDS))
    if missing or extra:
        raise SkillError(f"{skill_id}: missing or empty fields {missing}, unknown fields {extra}")
    if fields["name"] != skill_id:
        raise SkillError(f"{skill_id}: name {fields['name']!r} must equal the folder name")
    if fields["adapted_for"] != "nemotron":
        raise SkillError(f"{skill_id}: adapted_for must be 'nemotron'")
    roles_text = fields["roles"]
    if not (roles_text.startswith("[") and roles_text.endswith("]")):
        raise SkillError(f"{skill_id}: roles must be a list such as [coder, reviewer]")
    roles = tuple(r.strip() for r in roles_text[1:-1].split(",") if r.strip())
    if not roles:
        raise SkillError(f"{skill_id}: roles must not be empty")
    body = body.strip()
    if not body:
        raise SkillError(f"{skill_id}: the skill body is empty")
    return Skill(id=skill_id, body=body, **(fields | {"roles": roles}))


def load_skill(skill_id: str, skills_dir: Path = SKILLS_DIR) -> Skill:
    path = skills_dir / skill_id / "SKILL.md"
    if not path.is_file():
        raise SkillError(f"{skill_id}: {path} does not exist")
    return parse_skill(skill_id, path.read_text(encoding="utf-8"))


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    for key in ("skills", "roles"):
        if not isinstance(config.get(key), dict):
            raise SkillError(f"{path.name}: '{key}' must be an object")
    for role, spec in config["roles"].items():
        for skill_id in spec.get("skills", []):
            if skill_id not in config["skills"]:
                raise SkillError(f"{path.name}: role {role} uses unknown skill {skill_id}")
    return config


def skill_tokens(skill: Skill, config: dict[str, Any], model: str) -> tuple[int, TokenMethod]:
    """Measured prompt tokens on `model` when recorded, else an estimate (characters / 4)."""
    measured = config["skills"][skill.id].get("measured_prompt_tokens", {}).get(model)
    if measured is not None:
        return int(measured), "measured"
    return math.ceil(len(skill.render()) / 4), "estimate_chars_div_4"


def compose_system_prompt(
    role: str,
    base_prompt: str,
    *,
    config: dict[str, Any] | None = None,
    skills_dir: Path = SKILLS_DIR,
) -> ComposedPrompt:
    """The base prompt followed by the role's skills, in config order."""
    config = config if config is not None else load_config()
    spec = config["roles"].get(role)
    if spec is None:
        raise SkillError(f"role {role} is not in config/skills.json")
    skills = [load_skill(skill_id, skills_dir) for skill_id in spec["skills"]]
    tokens: dict[str, int] = {}
    methods: dict[str, TokenMethod] = {}
    for skill in skills:
        if role not in skill.roles:
            raise SkillError(f"skill {skill.id} is not written for role {role}")
        count, method = skill_tokens(skill, config, spec["model"])
        ceiling = config["skills"][skill.id]["max_tokens"]
        if count > ceiling:
            raise SkillError(f"skill {skill.id}: {count} tokens ({method}) > ceiling {ceiling}")
        tokens[skill.id], methods[skill.id] = count, method
    total, role_ceiling = sum(tokens.values()), spec["max_skill_tokens"]
    if total > role_ceiling:
        raise SkillError(f"role {role}: skills need {total} tokens > ceiling {role_ceiling}")
    text = "\n\n".join([base_prompt.strip(), *(skill.render() for skill in skills)])
    return ComposedPrompt(text, tuple(s.id for s in skills), tokens, methods)
