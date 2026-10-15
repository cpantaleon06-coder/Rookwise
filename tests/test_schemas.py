"""The contracts must accept the examples in docs/ARCHITECTURE.md exactly as written."""

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from rookwise.schemas import LedgerEntry, ResultV1, TaskV1

ARCHITECTURE = Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE.md"


def _examples() -> dict[str, dict]:
    """The JSON objects under "// task_v1", "// result_v1" and "// ledger_entry"."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    block = "// task_v1" + text.split("// task_v1", 1)[1].split("```", 1)[0]
    parts = re.split(r"^// (\w+).*$", block, flags=re.MULTILINE)[1:]
    return {name: json.loads(body) for name, body in zip(parts[::2], parts[1::2], strict=True)}


def test_architecture_examples_validate():
    examples = _examples()
    assert set(examples) == {"task_v1", "result_v1", "ledger_entry"}
    TaskV1.model_validate(examples["task_v1"])
    ResultV1.model_validate(examples["result_v1"])
    entry = LedgerEntry.model_validate(examples["ledger_entry"])
    assert entry.skills == []


def test_ledger_entry_round_trips_with_skills():
    data = _examples()["ledger_entry"] | {"skills": ["minimal-code"]}
    entry = LedgerEntry.model_validate(data)
    assert LedgerEntry.model_validate_json(entry.model_dump_json()) == entry
    assert entry.skills == ["minimal-code"]


def test_extra_fields_and_unknown_levels_are_rejected():
    examples = _examples()
    with pytest.raises(ValidationError):
        ResultV1.model_validate(examples["result_v1"] | {"content": "inline text"})
    with pytest.raises(ValidationError):
        LedgerEntry.model_validate(examples["ledger_entry"] | {"level": "harness"})
    with pytest.raises(ValidationError):
        TaskV1.model_validate(examples["task_v1"] | {"deadline_s": -1})
