"""The SYNTHETIC incident corpus (scripts/gen_incidents.py, benchmarks/incidents/) and the
deterministic scorer (core/incidents.py). No model, no network.

The logs are gitignored, so the tests rebuild the corpus in memory and write it to a
temporary directory; the committed files must match that build byte for byte.
"""

import importlib.util
import ipaddress
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from rookwise.evidence import Citation, Claim, check_citation, normalize_whitespace, verify
from rookwise.harness.cassette import find_secrets
from rookwise.incidents import (
    CATEGORIES,
    INCIDENTS_DIR,
    GroundTruth,
    covered_lines,
    incident_ids,
    load_bundle,
    load_ground_truth,
    score,
)

ROOT = Path(__file__).resolve().parents[1]
IDS = ["inc-01", "inc-02", "inc-03", "inc-04", "inc-05", "inc-06"]
KEYWORDS = re.compile(r"ERROR|WARN|FATAL", re.IGNORECASE)


def _generator():
    spec = importlib.util.spec_from_file_location(
        "gen_incidents", ROOT / "scripts" / "gen_incidents.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_incidents"] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


GEN = _generator()


@pytest.fixture(scope="module")
def corpus():
    return GEN.build_corpus()


@pytest.fixture(scope="module")
def corpus_dir(corpus, tmp_path_factory):
    out = tmp_path_factory.mktemp("incidents")
    GEN.write(out, corpus)
    return out


@pytest.fixture(scope="module")
def truths(corpus_dir):
    return {incident_id: load_ground_truth(incident_id, corpus_dir) for incident_id in IDS}


@pytest.fixture(scope="module")
def bundles(corpus_dir):
    return {incident_id: load_bundle(incident_id, corpus_dir) for incident_id in IDS}


def _refs(truth, *kinds):
    return [ref for kind in kinds for ref in getattr(truth, kind)]


def _cited_text(bundle, ref):
    return "\n".join(bundle.lines(ref.source_id)[ref.line_start - 1 : ref.line_end])


# -- the corpus -------------------------------------------------------------------------------


def test_regeneration_reproduces_the_manifest_and_the_committed_files(corpus):
    assert GEN.build_corpus() == corpus  # same seed, same bytes
    committed = (INCIDENTS_DIR / "manifest.json").read_text(encoding="utf-8")
    assert committed == corpus["manifest.json"]
    assert GEN.check(INCIDENTS_DIR, corpus) == []
    manifest = json.loads(committed)["files"]
    assert sorted(manifest) == sorted(p for p in corpus if p != "manifest.json")
    for path, info in manifest.items():
        assert info["committed"] is ("/logs/" not in path), path
        if info["committed"]:
            assert (INCIDENTS_DIR / path).read_text(encoding="utf-8") == corpus[path], path
    assert incident_ids() == IDS


def test_the_logs_are_gitignored_and_the_committed_part_stays_small(corpus):
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "benchmarks/incidents/*/logs/" in gitignore
    assert "benchmarks/incidents/** text eol=lf" in (ROOT / ".gitattributes").read_text("utf-8")
    committed = sum(len(t.encode()) for p, t in corpus.items() if "/logs/" not in p)
    assert committed < 200_000


def test_every_incident_has_the_required_files_and_shape(corpus, truths):
    for incident_id, truth in truths.items():
        files = {p.split("/", 1)[1] for p in corpus if p.startswith(f"{incident_id}/")}
        assert {
            "metrics.csv",
            "deploy.diff",
            "runbook.md",
            "ticket.md",
            "ground_truth.json",
        } <= files
        logs = sorted(f for f in files if f.startswith("logs/"))
        assert 2 <= len(logs) <= 3, incident_id
        assert any(f.endswith(".log") for f in logs) and any(f.endswith(".jsonl") for f in logs)
        lines = sum(corpus[f"{incident_id}/{f}"].count("\n") for f in logs)
        assert 5_000 <= lines <= 20_000 and lines == truth.log_lines, incident_id
        for name in files - {"ground_truth.json"}:  # its label is in its fields, checked below
            first = corpus[f"{incident_id}/{name}"].split("\n", 1)[0]
            assert "SYNTHETIC" in first, (incident_id, name)
        assert truth.synthetic is True and "SYNTHETIC" in truth.note
        assert len(truth.decoys) >= 2 and truth.acceptable_remediations
        assert set(truth.sources) == files - {"ground_truth.json"}


def test_every_ground_truth_ref_exists_and_contains_the_planted_text(truths, bundles):
    for incident_id, truth in truths.items():
        bundle = bundles[incident_id]
        for ref in _refs(truth, "essential_evidence", "supporting_evidence", "decoys"):
            assert ref.source_id in bundle.sources, (incident_id, ref)
            assert 1 <= ref.line_start <= ref.line_end <= len(bundle.lines(ref.source_id))
            cited = normalize_whitespace(_cited_text(bundle, ref).replace("\n", " "))
            assert normalize_whitespace(ref.quote) in cited, (incident_id, ref)


def test_ground_truth_citations_pass_and_corrupted_copies_fail(truths, bundles):
    for incident_id, truth in truths.items():
        bundle = bundles[incident_id]
        refs = _refs(truth, "essential_evidence", "supporting_evidence", "decoys")
        claims = [
            Claim(claim_id=f"c{i}", text="x", citations=[r.citation()]) for i, r in enumerate(refs)
        ]
        assert verify(bundle, claims).all_supported, incident_id
        for ref in refs:
            good = ref.citation()
            fabricated = good.model_copy(update={"quote": ref.quote + " (corrupted)"})
            moved = good.model_copy(
                update={"line_start": ref.line_end + 1, "line_end": ref.line_end + 1}
            )
            missing = good.model_copy(update={"source_id": "logs/not-there.log"})
            past_end = good.model_copy(update={"line_end": len(bundle.lines(ref.source_id)) + 1})
            assert check_citation(bundle, fabricated)[0] == "quote_not_found", ref
            assert check_citation(bundle, moved)[0] in ("quote_not_found", "line_out_of_range"), ref
            assert check_citation(bundle, missing)[0] == "source_missing", ref
            assert check_citation(bundle, past_end)[0] == "line_out_of_range", ref


def test_keyword_free_evidence_flags_hold_by_construction(truths, bundles):
    for incident_id, truth in truths.items():
        lines = [
            line
            for ref in truth.essential_evidence
            for line in _cited_text(bundles[incident_id], ref).split("\n")
        ]
        has_keyword = any(KEYWORDS.search(line) for line in lines)
        assert truth.keyword_free_evidence is not has_keyword, incident_id
    assert sum(t.keyword_free_evidence for t in truths.values()) >= 2


def test_the_split_categories_and_hard_cases_are_as_specified(truths):
    splits = {
        split: [i for i, t in truths.items() if t.split == split] for split in ("dev", "test")
    }
    assert splits == {"dev": ["inc-01", "inc-03", "inc-05"], "test": ["inc-02", "inc-04", "inc-06"]}
    for ids in splits.values():
        assert sorted(truths[i].difficulty for i in ids) == ["easy", "hard", "medium"]
    categories = [t.root_cause_category for t in truths.values()]
    assert len(set(categories)) == 6 and set(categories) < set(CATEGORIES)
    dev = {truths[i].root_cause_category for i in splits["dev"]}
    assert dev.isdisjoint(truths[i].root_cause_category for i in splits["test"])
    assert all(t.categories == list(CATEGORIES) for t in truths.values())
    assert tuple(GEN.CATEGORIES) == CATEGORIES
    assert any(t.cause_in_deploy_diff for t in truths.values())
    for truth in truths.values():
        in_diff = any(r.source_id == "deploy.diff" for r in truth.essential_evidence)
        assert truth.cause_in_deploy_diff is in_diff
    assert any(t.misleading_first_hypothesis for t in truths.values())
    for split, ids in splits.items():
        assert any(truths[i].keyword_free_evidence for i in ids), split


def test_decoys_are_alarming_errors(truths, bundles):
    for incident_id, truth in truths.items():
        for ref in truth.decoys:
            text = _cited_text(bundles[incident_id], ref)
            assert re.search(r"ERROR|FATAL", text, re.IGNORECASE), (incident_id, ref)


DOC_NETWORKS = [
    ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
]
REAL_TLD = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|dev|app|cloud|ai|co)\b", re.I)
SECRETS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}"),
    re.compile(r"\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[=:]", re.I),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abp]-[A-Za-z0-9-]{10,}"),
]


def test_no_real_looking_secrets_hosts_or_addresses(corpus):
    for path, text in corpus.items():
        assert find_secrets(text) == [], path
        for pattern in SECRETS:
            assert not pattern.search(text), (path, pattern.pattern)
        for address in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
            ip = ipaddress.ip_address(address)
            assert any(ip in net for net in DOC_NETWORKS), (path, address)
        for match in REAL_TLD.finditer(text):
            host = match.group(0).lower()
            assert host.endswith((".example.com", ".example.net", ".example.org")) or host in (
                "example.com",
                "example.net",
                "example.org",
            ), (path, host)


# -- load_bundle -----------------------------------------------------------------------------


def test_load_bundle_has_stable_source_ids_and_one_based_lines(bundles, truths, corpus):
    bundle = bundles["inc-03"]
    assert list(bundle.sources) == [
        "deploy.diff",
        "logs/cart-svc.jsonl",
        "logs/storefront-api.log",
        "metrics.csv",
        "runbook.md",
        "ticket.md",
    ]
    assert "ground_truth.json" not in bundle.sources
    for ref in truths["inc-03"].essential_evidence:
        assert ref.quote in bundle.lines(ref.source_id)[ref.line_start - 1]
    assert bundle.lines("metrics.csv")[1].startswith("ts,")  # line 1 is the SYNTHETIC note
    assert bundle.sources["metrics.csv"] == corpus["inc-03/metrics.csv"]


def test_load_bundle_refuses_a_changed_or_missing_file(corpus_dir, tmp_path):
    copy = tmp_path / "incidents"
    shutil.copytree(corpus_dir, copy)
    log = copy / "inc-01" / "logs" / "billing-api.log"
    log.write_text(log.read_text(encoding="utf-8") + "extra line\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        load_bundle("inc-01", copy)
    (copy / "inc-02" / "logs" / "catalog-api.log").unlink()
    with pytest.raises(FileNotFoundError, match="gen_incidents.py"):
        load_bundle("inc-02", copy)
    with pytest.raises(KeyError):
        load_bundle("inc-99", copy)


def test_ground_truth_files_validate_against_the_model(corpus):
    for incident_id in IDS:
        GroundTruth.model_validate_json(corpus[f"{incident_id}/ground_truth.json"])


# -- the scorer -------------------------------------------------------------------------------


def _claims_for(refs, quote=None):
    return [
        Claim(
            claim_id=f"c{i}",
            text="[stub] a finding",
            citations=[ref.citation().model_copy(update={"quote": quote(ref)} if quote else {})],
        )
        for i, ref in enumerate(refs)
    ]


def test_a_correct_diagnosis_scores_as_correct(truths, bundles):
    for incident_id, truth in truths.items():
        result = score(
            _claims_for(truth.essential_evidence),
            truth,
            category=truth.root_cause_category,
            bundle=bundles[incident_id],
        )
        assert result.diagnosis_correct and result.category_correct, incident_id
        assert result.citation_verified_rate == 1.0 and result.evidence_recall == 1.0
        assert result.essential_covered == list(range(len(truth.essential_evidence)))


def test_a_short_quote_from_the_essential_line_counts(truths, bundles):
    truth = truths["inc-03"]
    ref = truth.essential_evidence[0]  # the config line: quote only the changed value
    claims = _claims_for([ref], quote=lambda r: "cart_client.timeout_ms=30")
    result = score(claims, truth, category="bad_config", bundle=bundles["inc-03"])
    assert result.diagnosis_correct
    assert result.evidence_recall == pytest.approx(1 / len(truth.essential_evidence))


def test_the_right_category_with_fabricated_citations_is_not_correct(truths, bundles):
    truth = truths["inc-04"]
    claims = _claims_for(truth.essential_evidence, quote=lambda r: r.quote.replace("4", "9"))
    result = score(claims, truth, category=truth.root_cause_category, bundle=bundles["inc-04"])
    assert result.category_correct and not result.diagnosis_correct
    assert result.citation_verified_rate == 0.0 and result.evidence_recall == 0.0
    assert result.evidence.unsupported_claims == [c.claim_id for c in claims]


def test_the_wrong_category_with_real_citations_is_not_correct(truths, bundles):
    truth = truths["inc-04"]  # the misleading hypothesis: blame the app deploy
    result = score(
        _claims_for(truth.essential_evidence),
        truth,
        category="code_regression",
        bundle=bundles["inc-04"],
    )
    assert not result.category_correct and not result.diagnosis_correct
    assert result.citation_verified_rate == 1.0 and result.evidence_recall == 1.0


def test_citing_only_decoys_or_supporting_lines_is_not_correct(truths, bundles):
    truth = truths["inc-05"]
    claims = _claims_for(truth.decoys + truth.supporting_evidence)
    result = score(claims, truth, category=truth.root_cause_category, bundle=bundles["inc-05"])
    assert result.citation_verified_rate == 1.0
    assert not result.diagnosis_correct and result.evidence_recall == 0.0


def test_a_wide_range_with_a_quote_from_another_line_covers_nothing(truths, bundles):
    truth = truths["inc-01"]
    bundle = bundles["inc-01"]
    ref = truth.essential_evidence[1]
    lines = bundle.lines(ref.source_id)
    wide = Citation(
        source_id=ref.source_id,
        line_start=ref.line_start - 5,
        line_end=ref.line_end + 5,
        quote=lines[ref.line_start - 6],  # the first line of the range, not the essential one
    )
    assert check_citation(bundle, wide)[0] == "ok"
    assert ref.line_start not in covered_lines(bundle, wide)
    result = score(
        [Claim(claim_id="c1", text="x", citations=[wide])],
        truth,
        category="certificate_expiry",
        bundle=bundle,
    )
    assert result.citation_verified_rate == 1.0 and not result.diagnosis_correct


def test_one_row_inside_a_metrics_range_covers_that_ref(truths, bundles):
    truth = truths["inc-05"]
    ref = next(r for r in truth.essential_evidence if r.source_id == "metrics.csv")
    row = ref.line_start + 2
    citation = Citation(
        source_id="metrics.csv",
        line_start=row,
        line_end=row,
        quote=bundles["inc-05"].lines("metrics.csv")[row - 1],
    )
    claims = [Claim(claim_id="c1", text="x", citations=[citation])]
    result = score(claims, truth, category="capacity_exhaustion", bundle=bundles["inc-05"])
    assert result.diagnosis_correct and result.essential_covered == [
        truth.essential_evidence.index(ref)
    ]


def test_no_claims_and_unknown_categories_score_zero(truths, bundles):
    truth = truths["inc-02"]
    empty = score([], truth, category="resource_leak", bundle=bundles["inc-02"])
    assert (empty.diagnosis_correct, empty.citation_verified_rate, empty.evidence_recall) == (
        False,
        0.0,
        0.0,
    )
    unknown = score(
        _claims_for(truth.essential_evidence), truth, category="gremlins", bundle=bundles["inc-02"]
    )
    assert not unknown.diagnosis_correct and unknown.evidence_recall == 1.0
    none = score(
        _claims_for(truth.essential_evidence), truth, category=None, bundle=bundles["inc-02"]
    )
    assert not none.diagnosis_correct


def test_the_scorer_is_deterministic_and_reads_the_corpus_when_no_bundle_is_given(
    truths, corpus_dir
):
    truth = truths["inc-06"]
    claims = _claims_for(truth.essential_evidence)
    first = score(claims, truth, category="disk_exhaustion", root=corpus_dir)
    second = score(claims, truth, category="disk_exhaustion", root=corpus_dir)
    assert first == second and first.diagnosis_correct
