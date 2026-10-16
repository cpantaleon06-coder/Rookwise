"""The harness is the only code in core/ that may call the model API."""

import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"
HTTP_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:httpx|openai|requests|aiohttp)\b", re.M)


def test_only_the_harness_imports_an_http_or_model_client():
    offenders = [
        path.relative_to(CORE).as_posix()
        for path in CORE.rglob("*.py")
        if "harness" not in path.relative_to(CORE).parts
        and (
            HTTP_IMPORT.search(text := path.read_text(encoding="utf-8"))
            or "tokenfactory" in text.lower()
        )
    ]
    assert offenders == []
