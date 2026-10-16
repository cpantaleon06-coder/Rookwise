"""Generate the API v1 JSON Schemas in docs/api/schemas/ from the pydantic models in
core/api/models.py (which reuse the models in core/schemas.py and core/harness).

One file per top-level payload, plus SseEvent.json for the event union. The test
tests/test_api_contract.py fails when a committed schema drifts from its model.

Usage:
    python scripts/gen_api_schemas.py           # write the files
    python scripts/gen_api_schemas.py --check   # exit 1 if any file differs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # noqa: E402 (lets `rookwise` resolve from a checkout)

from rookwise.api.models import SCHEMA_MODELS, SSE_EVENT_ADAPTER  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "docs" / "api" / "schemas"
BASE_ID = "https://github.com/cpantaleon06-coder/Rookwise/blob/main/docs/api/schemas/"


def _with_header(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_ID}{name}.json",
        **schema,
    }


def schemas() -> dict[str, str]:
    out = {
        name: _with_header(name, model.model_json_schema()) for name, model in SCHEMA_MODELS.items()
    }
    out["SseEvent"] = _with_header("SseEvent", SSE_EVENT_ADAPTER.json_schema())
    return {
        f"{name}.json": json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        for name, schema in out.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    wanted = schemas()
    if args.check:
        stale = [
            name
            for name, text in wanted.items()
            if not (SCHEMA_DIR / name).exists()
            or (SCHEMA_DIR / name).read_text(encoding="utf-8") != text
        ]
        extra = sorted(p.name for p in SCHEMA_DIR.glob("*.json") if p.name not in wanted)
        if stale or extra:
            print(f"stale: {stale}, extra: {extra}")
            return 1
        print(f"{len(wanted)} schemas up to date")
        return 0
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in wanted.items():
        (SCHEMA_DIR / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(wanted)} schemas to {SCHEMA_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
