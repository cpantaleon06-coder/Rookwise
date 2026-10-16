"""Boundaries in core/.

1. Only core/harness/ may call the model API: no other module mentions the Token
   Factory host or imports the OpenAI SDK.
2. HTTP clients are allowed only in core/harness/ and in the explicit allowlist below.
   core/tools/ is allowed because tools call their own APIs (Tavily search); a tool
   still never reaches the model API, which rule 1 checks.
"""

import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"
HTTP_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:httpx|openai|requests|aiohttp)\b", re.M)
OPENAI_IMPORT = re.compile(r"^\s*(?:import|from)\s+openai\b", re.M)
# Folders under core/ (besides harness/) whose modules may import an HTTP client.
HTTP_ALLOWLIST = ("tools",)


def _modules():
    for path in CORE.rglob("*.py"):
        parts = path.relative_to(CORE).parts
        yield path, parts, path.read_text(encoding="utf-8")


def test_only_the_harness_reaches_the_model_api():
    offenders = [
        "/".join(parts)
        for path, parts, text in _modules()
        if parts[0] != "harness" and ("tokenfactory" in text.lower() or OPENAI_IMPORT.search(text))
    ]
    assert offenders == []


def test_http_clients_only_in_the_harness_and_the_allowlist():
    offenders = [
        "/".join(parts)
        for path, parts, text in _modules()
        if parts[0] not in ("harness", *HTTP_ALLOWLIST) and HTTP_IMPORT.search(text)
    ]
    assert offenders == []


def test_the_allowlist_is_still_needed():
    # Keep the allowlist honest: every allowed folder exists and uses an HTTP client.
    for folder in HTTP_ALLOWLIST:
        texts = [t for _, parts, t in _modules() if parts[0] == folder]
        assert texts and any(HTTP_IMPORT.search(t) for t in texts), folder
