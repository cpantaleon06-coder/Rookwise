"""Tavily search tool against a mock transport. No network, no real key."""

import json

import httpx
import pytest
from harness_support import run

from rookwise.harness.loop import ToolContext
from rookwise.tools.tavily import TAVILY_URL, TOOL_NAME, TavilyError, TavilySearch

FAKE_KEY = "fake-tavily-key-for-tests"
CTX = ToolContext("r-1", "t-1")


def _client(status=200, body=None, seen=None, key=FAKE_KEY):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        reply = (
            body
            if body is not None
            else {
                "query": "q",
                "results": [
                    {"title": "A", "url": "https://a.example", "content": "x" * 5000, "score": 0.9},
                    {"title": "B", "url": "https://b.example", "content": "b"},
                ],
            }
        )
        return httpx.Response(status, json=reply)

    return TavilySearch(key, transport=httpx.MockTransport(handler))


def test_search_sends_the_query_and_returns_title_url_content():
    seen = []

    async def main():
        tavily = _client(seen=seen)
        result = await tavily.search({"query": " nemotron ", "max_results": 50}, CTX)
        await tavily.aclose()
        return result

    result = run(main())
    (request,) = seen
    assert str(request.url) == TAVILY_URL
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert json.loads(request.content) == {"query": "nemotron", "max_results": 10}
    assert [r["title"] for r in result["results"]] == ["A", "B"]
    assert set(result["results"][0]) == {"title", "url", "content"}
    assert len(result["results"][0]["content"]) == 1000


def test_queries_are_counted_per_run():
    async def main():
        tavily = _client()
        await tavily.search({"query": "a"}, CTX)
        await tavily.search({"query": "b"}, CTX)
        await tavily.search({"query": "c"}, ToolContext("r-2", "t-1"))
        await tavily.aclose()
        return tavily

    tavily = run(main())
    assert tavily.query_count("r-1") == 2 and tavily.query_count("r-2") == 1
    assert tavily.query_count("r-3") == 0


def test_missing_key_makes_the_tool_unavailable_without_crashing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    tavily = TavilySearch()
    tool = tavily.tool()
    assert tool.name == TOOL_NAME
    assert "TAVILY_API_KEY" in tool.unavailable_reason()

    async def main():
        with pytest.raises(TavilyError, match="TAVILY_API_KEY"):
            await tavily.search({"query": "x"}, CTX)
        await tavily.aclose()

    run(main())
    assert tavily.query_count("r-1") == 0


def test_errors_and_bad_arguments_raise_for_the_loop_to_report():
    async def main():
        failing = _client(status=401, body={"detail": "bad key"})
        with pytest.raises(TavilyError, match="HTTP 401"):
            await failing.search({"query": "x"}, CTX)
        odd = _client(body={"answer": "no results key"})
        with pytest.raises(TavilyError, match="results"):
            await odd.search({"query": "x"}, CTX)
        with pytest.raises(ValueError):
            await odd.search({"query": "  "}, CTX)
        with pytest.raises(ValueError):
            await odd.search({"query": "x", "max_results": "5"}, CTX)
        await failing.aclose()
        await odd.aclose()

    run(main())


def test_the_reply_shape_seen_in_the_tavily_probe_parses():
    # Keys and value types as observed on 2026-10-16 (HARNESS_RESEARCH.md, "Tavily probe");
    # the values are made up.
    observed = {
        "query": "q",
        "follow_up_questions": None,
        "answer": None,
        "images": [],
        "results": [
            {
                "url": "https://a.example",
                "title": "A",
                "content": "Paris.",
                "score": 0.98,
                "raw_content": None,
                "id": "abc123def",
            }
        ],
        "response_time": 0.8,
        "request_id": "req-1",
    }

    async def main():
        tavily = _client(body=observed)
        result = await tavily.search({"query": "q", "max_results": 3}, CTX)
        await tavily.aclose()
        return result

    assert run(main()) == {
        "results": [{"title": "A", "url": "https://a.example", "content": "Paris."}]
    }
