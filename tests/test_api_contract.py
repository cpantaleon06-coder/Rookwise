"""API v1 contract: the committed JSON Schemas match the pydantic models. No network."""

import importlib.util
import json
from pathlib import Path

import pytest

from rookwise.api import EVENT_TYPES
from rookwise.api.models import CreateRunRequest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "api" / "schemas"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_schemas_match_the_models():
    wanted = _script("gen_api_schemas").schemas()
    on_disk = {p.name: p.read_text(encoding="utf-8") for p in SCHEMA_DIR.glob("*.json")}
    assert sorted(on_disk) == sorted(wanted)
    for name, text in wanted.items():
        assert json.loads(on_disk[name]) == json.loads(text), name


def test_every_event_type_has_a_schema():
    schema = json.loads((SCHEMA_DIR / "SseEvent.json").read_text(encoding="utf-8"))
    mapped = set(schema["discriminator"]["mapping"])
    assert mapped == set(EVENT_TYPES)


def test_create_run_request_rules():
    CreateRunRequest(mode="recorded", recording_id="rec-1")
    CreateRunRequest(mode="live", goal="g", budget_usd=0.1)
    with pytest.raises(ValueError):
        CreateRunRequest(mode="live", goal="g")
    with pytest.raises(ValueError):
        CreateRunRequest(mode="recorded")
    with pytest.raises(ValueError):
        CreateRunRequest(mode="live", goal="g", budget_usd=0.1, api_key="nope")
