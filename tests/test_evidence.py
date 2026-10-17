"""Deterministic evidence verification (core/evidence.py). Neutral placeholder sources,
no model, no network."""

import pytest

from rookwise.evidence import (
    Citation,
    Claim,
    EvidenceBundle,
    EvidenceReport,
    check_citation,
    split_lines,
    verify,
)

SOURCE = (
    "Sample record one: the widget weighs 12 units.\n"
    "Sample record two: the widget is blue\n"
    "and ships in a box of four.\n"
    "Sample record three: no other colours exist.\n"
)
BUNDLE = EvidenceBundle(sources={"src-a": SOURCE, "src-b": "Only one line here."})


def cite(quote, start=1, end=None, source="src-a"):
    return Citation(source_id=source, line_start=start, line_end=end or start, quote=quote)


def reason(citation, bundle=BUNDLE):
    return check_citation(bundle, citation)[0]


def test_an_exact_quote_on_the_cited_line_is_ok():
    assert reason(cite("the widget weighs 12 units.", 1)) == "ok"
    report = verify(
        BUNDLE, [Claim(claim_id="c-1", text="It weighs 12.", citations=[cite("weighs 12 units")])]
    )
    assert report.all_supported and report.citation_verified_rate == 1.0
    assert report.claims[0].reason == "ok" and report.claims[0].citations[0].ok


def test_a_fabricated_quote_is_not_found():
    reason_code, detail = check_citation(BUNDLE, cite("the widget weighs 15 units.", 1))
    assert (reason_code, detail) == ("quote_not_found", "the quote is not in the source")


def test_a_wrong_source_is_missing():
    assert reason(cite("the widget weighs 12 units.", 1, source="src-z")) == "source_missing"
    # The quote exists, but in another source than the one cited.
    assert reason(cite("the widget weighs 12 units.", 1, source="src-b")) == "quote_not_found"


def test_an_off_by_one_line_range_is_caught():
    reason_code, detail = check_citation(BUNDLE, cite("no other colours exist.", 3))
    assert reason_code == "quote_not_found"
    assert detail == "the quote is in the source but not in lines 3-3"
    assert reason(cite("no other colours exist.", 4)) == "ok"
    assert reason(cite("no other colours exist.", 4, 5)) == "line_out_of_range"
    assert reason(cite("no other colours exist.", 5)) == "line_out_of_range"


def test_line_numbers_are_one_based_and_ranges_must_be_ordered():
    assert reason(cite("Sample record one", 1)) == "ok"
    assert reason(cite("Sample record one", 0, 1)) == "line_out_of_range"
    assert reason(cite("Sample record one", -1, 1)) == "line_out_of_range"
    assert reason(cite("Sample record two", 2, 1)) == "line_out_of_range"


def test_a_quote_spanning_a_line_boundary_needs_both_lines_cited():
    quote = "the widget is blue and ships in a box of four."
    assert reason(cite(quote, 2, 3)) == "ok"
    assert reason(cite(quote, 2)) == "quote_not_found"
    assert reason(cite(quote, 3)) == "quote_not_found"
    # Written with the line break inside the quote, it is the same quote.
    assert reason(cite("the widget is blue\nand ships", 2, 3)) == "ok"


def test_a_partial_quote():
    # A fragment that is really in the cited line is a valid quote.
    assert reason(cite("weighs 12", 1)) == "ok"
    # A quote that starts like the source and then goes its own way is not.
    assert reason(cite("the widget weighs 12 units and is red.", 1)) == "quote_not_found"
    # Only half a word matches: no fuzzy matching, so a wrong word fails.
    assert reason(cite("the widget weigh 12 units", 1)) == "quote_not_found"


def test_extra_whitespace_is_normalized_and_nothing_else():
    assert reason(cite("  the   widget\tweighs \n 12   units. ", 1)) == "ok"
    spaced = EvidenceBundle(sources={"s": "The   value\t is   seven.\r\nNext line.\r\n"})
    assert reason(cite("The value is seven.", 1, source="s"), spaced) == "ok"
    assert reason(cite("Next line.", 2, source="s"), spaced) == "ok"
    # No case folding and no punctuation normalization.
    assert reason(cite("THE WIDGET weighs 12 units.", 1)) == "quote_not_found"
    assert reason(cite("the widget weighs 12 units!", 1)) == "quote_not_found"


def test_an_empty_quote_is_never_found():
    assert check_citation(BUNDLE, cite("   ", 1)) == ("quote_not_found", "the quote is empty")


def test_an_empty_bundle_supports_nothing():
    claims = [
        Claim(claim_id="c-1", text="One.", citations=[cite("the widget weighs 12 units.", 1)]),
        Claim(claim_id="c-2", text="Two.", citations=[cite("anything", 1, source="src-b")]),
    ]
    report = verify(EvidenceBundle(), claims)
    assert [c.reason for c in report.claims] == ["source_missing", "source_missing"]
    assert report.unsupported_claims == ["c-1", "c-2"]
    assert (report.citations_total, report.citations_verified) == (2, 0)
    assert report.citation_verified_rate == 0.0


def test_a_claim_with_no_citations_is_unsupported():
    report = verify(BUNDLE, [Claim(claim_id="c-1", text="Uncited.")])
    (claim,) = report.claims
    assert (claim.supported, claim.reason, claim.citations) == (False, "no_citations", [])
    assert report.unsupported_claims == ["c-1"]
    assert report.citations_total == 0 and report.citation_verified_rate == 0.0
    assert verify(BUNDLE, []).citation_verified_rate == 0.0


def test_one_bad_citation_makes_a_claim_unsupported_and_the_rate_counts_citations():
    good = cite("the widget weighs 12 units.", 1)
    claims = [
        Claim(claim_id="c-1", text="Mixed.", citations=[good, cite("weighs 12 units.", 2)]),
        Claim(
            claim_id="c-2", text="Good.", citations=[good, cite("Only one line", 1, source="src-b")]
        ),
    ]
    report = verify(BUNDLE, claims)
    assert [c.supported for c in report.claims] == [False, True]
    assert report.claims[0].reason == "quote_not_found"
    assert [c.reason for c in report.claims[0].citations] == ["ok", "quote_not_found"]
    assert [c.index for c in report.claims[0].citations] == [0, 1]
    assert report.unsupported_claims == ["c-1"]
    assert (report.citations_total, report.citations_verified) == (4, 3)
    assert report.citation_verified_rate == 0.75


def test_line_splitting():
    assert split_lines("") == []
    assert split_lines("a") == ["a"]
    assert split_lines("a\n") == ["a"]
    assert split_lines("a\n\n") == ["a", ""]
    assert split_lines("a\r\nb\rc\n") == ["a", "b", "c"]
    # Only \n, \r\n and \r end a line; a form feed does not.
    assert split_lines("a\x0cb") == ["a\x0cb"]


def test_duplicate_claim_ids_are_refused():
    with pytest.raises(ValueError, match="unique"):
        verify(BUNDLE, [Claim(claim_id="c-1", text="A."), Claim(claim_id="c-1", text="B.")])


def test_the_report_is_deterministic_and_round_trips_as_json():
    claims = [
        Claim(claim_id=f"c-{i}", text="x", citations=[cite("Sample record", line)])
        for i, line in enumerate([1, 2, 4, 9])
    ]
    first, second = verify(BUNDLE, claims), verify(BUNDLE, claims)
    assert first == second
    assert EvidenceReport.model_validate_json(first.model_dump_json()) == first
    assert [c.reason for c in first.claims] == ["ok", "ok", "ok", "line_out_of_range"]


def test_claims_and_citations_validate_from_model_output():
    raw = {
        "claim_id": "c-1",
        "text": "It is blue.",
        "citations": [{"source_id": "src-a", "line_start": 2, "line_end": 2, "quote": "is blue"}],
    }
    claim = Claim.model_validate(raw)
    assert verify(BUNDLE, [claim]).all_supported
    with pytest.raises(ValueError):
        Claim.model_validate(raw | {"confidence": 0.9})
