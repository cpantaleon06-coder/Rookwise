"""SSE decoding and chunk normalization, with chunks shaped like the streaming probe saw them."""

import pytest
from harness_support import (
    chunk,
    content,
    final_usage,
    finish,
    reasoning,
    role,
    sse,
    tool_call,
    usage,
)

from rookwise.harness.events import (
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    assemble_tool_calls,
)
from rookwise.harness.retry import ApiError
from rookwise.harness.sse import ChunkNormalizer, SSEDecoder
from rookwise.ledger import Usage


def _decode_all(parts: list[bytes]) -> list[str]:
    decoder = SSEDecoder()
    payloads: list[str] = []
    for part in parts:
        payloads.extend(decoder.feed(part))
    return payloads + decoder.flush()


def test_events_split_across_reads_decode_the_same():
    body = sse([role(), content("héllo"), finish(), final_usage()])
    whole = _decode_all([body])
    assert whole[-1] == "[DONE]" and len(whole) == 5
    assert _decode_all([body[i : i + 1] for i in range(len(body))]) == whole
    assert _decode_all([body[:7], body[7:50], body[50:]]) == whole


def test_crlf_comments_multiline_data_and_missing_final_blank_line():
    body = b': keep-alive\r\ndata: {"a":\r\ndata: 1}\r\n\r\nevent: x\ndata: [DONE]'
    assert _decode_all([body]) == ['{"a":\n1}', "[DONE]"]


def test_role_and_empty_deltas_yield_nothing():
    normalizer = ChunkNormalizer(["reasoning_content", "reasoning"])
    assert normalizer.feed(role()) == []
    assert normalizer.feed(chunk([{"index": 0, "delta": {"content": None}}])) == []
    assert normalizer.feed(chunk([{"index": 0, "delta": {}}])) == []
    assert normalizer.feed(content("1")) == [TextDelta(text="1")]


def test_reasoning_sent_in_two_fields_counts_once():
    normalizer = ChunkNormalizer(["reasoning_content", "reasoning"])
    both = normalizer.feed(reasoning("think", ("reasoning", "reasoning_content")))
    assert both == [ReasoningDelta(text="think")]
    assert normalizer.feed(reasoning("nano", ("reasoning",))) == [ReasoningDelta(text="nano")]


def test_final_usage_comes_from_the_empty_choices_chunk():
    normalizer = ChunkNormalizer(["reasoning"])
    normalizer.feed(chunk([{"index": 0, "delta": {"content": "1"}}], usage(35, 1)))
    assert normalizer.outcome.final_usage() is None
    assert normalizer.outcome.running_usage == Usage(35, 1)
    normalizer.feed(finish())
    normalizer.feed(final_usage(prompt=35, completion=21, cached=5, reasoning_tokens=3))
    normalizer.feed("[DONE]")
    outcome = normalizer.outcome
    assert outcome.done and outcome.finish_reason == "stop"
    assert outcome.final_usage() == Usage(35, 21, cached_tokens=5, reasoning_tokens=3)


def test_running_usage_is_not_final_when_the_stream_is_cut():
    normalizer = ChunkNormalizer(["reasoning"])
    normalizer.feed(chunk([{"index": 0, "delta": {"content": "1"}}], usage(38, 7)))
    assert normalizer.outcome.final_usage() is None


def test_usage_on_the_finish_chunk_counts_once_done_is_seen():
    normalizer = ChunkNormalizer(["reasoning"])
    normalizer.feed(chunk([{"index": 0, "delta": {}, "finish_reason": "length"}], usage(10, 64)))
    assert normalizer.outcome.final_usage() is None
    normalizer.feed("[DONE]")
    assert normalizer.outcome.final_usage() == Usage(10, 64)


def test_error_chunk_and_bad_json_raise():
    normalizer = ChunkNormalizer(["reasoning"])
    with pytest.raises(ApiError) as caught:
        normalizer.feed('{"error": {"message": "overloaded", "code": 503}}')
    assert caught.value.kind == "server"
    with pytest.raises(ApiError) as caught:
        normalizer.feed("{not json")
    assert caught.value.kind == "protocol"


def _tool_events(payloads: list[str]) -> list[ToolCallDelta]:
    normalizer = ChunkNormalizer(["reasoning"])
    events = [e for p in payloads for e in normalizer.feed(p)]
    assert all(isinstance(e, ToolCallDelta) for e in events)
    return events


def test_tool_call_fragments_like_ultra_assemble():
    events = _tool_events(
        [
            tool_call(id="chatcmpl-tool-1", name="add", arguments=None),
            tool_call(arguments='{"a": '),
            tool_call(arguments='17, "b": '),
            tool_call(arguments="25}"),
        ]
    )
    assert events[0] == ToolCallDelta(index=0, id="chatcmpl-tool-1", name="add")
    assert assemble_tool_calls(events) == (
        ToolCall(id="chatcmpl-tool-1", name="add", arguments='{"a": 17, "b": 25}'),
    )


def test_tool_call_in_one_piece_like_lightning_and_late_null_id_like_nano():
    lightning = _tool_events(
        [tool_call(id="call_1", name="add", arguments=None), tool_call(arguments='{"a":1}')]
    )
    assert assemble_tool_calls(lightning)[0].arguments == '{"a":1}'
    nano = _tool_events(
        [
            tool_call(id="call_2", name="add", arguments=""),
            tool_call(arguments="{"),
            tool_call(arguments='"a": 1'),
            chunk(
                [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": None,
                                    "type": "function",
                                    "function": {"arguments": "}"},
                                }
                            ]
                        },
                    }
                ]
            ),
        ]
    )
    assert assemble_tool_calls(nano) == (ToolCall(id="call_2", name="add", arguments='{"a": 1}'),)


def test_parallel_tool_calls_keep_their_index():
    events = _tool_events(
        [
            tool_call(index=0, id="a", name="add", arguments="{}"),
            tool_call(index=1, id="b", name="mul", arguments="{}"),
        ]
    )
    assert [c.name for c in assemble_tool_calls(events)] == ["add", "mul"]


def test_tool_call_stream_ends_with_tool_calls_finish():
    body = sse([role(), tool_call(id="c", name="add", arguments="{}"), finish("tool_calls")])
    decoder = SSEDecoder()
    normalizer = ChunkNormalizer(["reasoning"])
    for payload in decoder.feed(body):
        normalizer.feed(payload)
    assert normalizer.outcome.finish_reason == "tool_calls" and normalizer.outcome.done
