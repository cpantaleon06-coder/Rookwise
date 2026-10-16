"""Tavily web search as a harness tool: `search(query, max_results)`.

The key is read from `TAVILY_API_KEY` in the environment (or passed in) and never
logged. Without a key the tool is unavailable: the loop does not offer it, and a call
returns an `unavailable` error to the model instead of failing the run.

API shape, UNVERIFIED in this repo (no live Tavily call has been made yet; from Tavily's
public docs): `POST https://api.tavily.com/search` with a JSON body
`{"query", "max_results"}` and the key in an `Authorization: Bearer` header; the reply
has a `results` list of objects with `title`, `url` and `content`. Only those three
fields are passed back to the model.

Cost: Tavily bills by its own plan, not from the Nebius credits. No dollar price is
recorded here (UNVERIFIED); queries are counted per run instead (`query_count`), and the
tool loop counts calls per tool name in its outcome, which is what the run record uses.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Any

import httpx

from rookwise.harness.loop import Tool, ToolContext

TAVILY_URL = "https://api.tavily.com/search"
TOOL_NAME = "search"
DEFAULT_MAX_RESULTS = 5
MAX_RESULTS_CAP = 10
CONTENT_CHARS = 1_000

PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "What to search the web for."},
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_RESULTS_CAP,
            "description": f"How many results to return (default {DEFAULT_MAX_RESULTS}).",
        },
    },
    "required": ["query"],
}


class TavilyError(RuntimeError):
    """Tavily refused or failed a search. The loop turns it into a tool error."""


class TavilySearch:
    """One Tavily client. Holds its own counters; create one per run executor."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("TAVILY_API_KEY", "")
        self._key = key.strip()
        self._queries: Counter[str] = Counter()
        self._http = httpx.AsyncClient(timeout=timeout_s, transport=transport)

    def unavailable(self) -> str | None:
        return None if self._key else "TAVILY_API_KEY is not set: web search is unavailable"

    def query_count(self, run_id: str) -> int:
        """Queries sent to Tavily for a run (not counting refused calls)."""
        return self._queries[run_id]

    def tool(self, timeout_s: float | None = None) -> Tool:
        return Tool(
            name=TOOL_NAME,
            description="Search the web and return the top results (title, url, content).",
            parameters=PARAMETERS,
            handler=self.search,
            timeout_s=timeout_s,
            unavailable=self.unavailable,
        )

    async def search(self, args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        reason = self.unavailable()
        if reason is not None:
            raise TavilyError(reason)
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        max_results = args.get("max_results", DEFAULT_MAX_RESULTS)
        if not isinstance(max_results, int) or isinstance(max_results, bool):
            raise ValueError("max_results must be an integer")
        max_results = min(max(max_results, 1), MAX_RESULTS_CAP)
        self._queries[context.run_id] += 1
        response = await self._http.post(
            TAVILY_URL,
            json={"query": query.strip(), "max_results": max_results},
            headers={"Authorization": f"Bearer {self._key}"},
        )
        if response.status_code != 200:
            raise TavilyError(f"HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise TavilyError("the reply has no results list")
        return {
            "results": [
                {
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "content": str(item.get("content") or "")[:CONTENT_CHARS],
                }
                for item in results[:max_results]
                if isinstance(item, dict)
            ]
        }

    async def aclose(self) -> None:
        await self._http.aclose()
