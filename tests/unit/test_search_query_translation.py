"""Database-specific query translation from the conceptual boolean structure."""

from __future__ import annotations

from src.models import ReviewConfig, ReviewType
from src.search.query_translation import parse_conceptual_query
from src.search.strategy import (
    build_conceptual_query,
    build_database_query,
    build_relaxed_database_query,
)

_OVERRIDE = (
    '("agentic AI" OR "AI agent" OR "multi-agent system") AND ("exception handling" OR "decision support" OR workflow)'
)


def _review(overrides: dict[str, str] | None = None, review_type: ReviewType = ReviewType.SYSTEMATIC) -> ReviewConfig:
    return ReviewConfig(
        research_question="How are agentic systems designed to manage operational exceptions in organisations?",
        review_type=review_type,
        pico={
            "population": "organisations",
            "intervention": "agentic AI systems",
            "comparison": "none",
            "outcome": "exception handling outcomes",
        },
        keywords=["agentic AI", "AI agent", "exception handling", "workflow"],
        domain="information systems",
        scope="organisational operations",
        inclusion_criteria=["empirical studies"],
        exclusion_criteria=["not relevant"],
        date_range_start=2000,
        date_range_end=2026,
        target_databases=["semantic_scholar", "openalex", "crossref", "arxiv", "dblp", "core"],
        search_overrides=overrides,
        **(
            {"pcc": {"population": "organisations", "concept": "agentic AI", "context": "operations"}}
            if review_type == ReviewType.SCOPING
            else {}
        ),
    )


def test_parse_scopus_flavoured_override_into_groups() -> None:
    q = 'TITLE-ABS-KEY("a b" OR "c") AND TITLE-ABS-KEY("d" OR e) AND PUBYEAR > 1999 AND PUBYEAR < 2027'
    cq = parse_conceptual_query(q)
    assert [[t.text for t in g] for g in cq.groups] == [["a b", "c"], ["d", "e"]]


def test_parse_not_is_left_unstructured() -> None:
    cq = parse_conceptual_query('"a" AND NOT "b"')
    assert not cq.is_structured
    assert cq.raw == '"a" AND NOT "b"'


def test_semantic_scholar_boolean_override_translated_to_bulk_syntax() -> None:
    q = build_database_query(_review({"semantic_scholar": _OVERRIDE}), "semantic_scholar")
    assert q == (
        '("agentic AI" | "AI agent" | "multi-agent system") + ("exception handling" | "decision support" | workflow)'
    )
    assert " AND " not in q and " OR " not in q


def test_semantic_scholar_native_override_used_verbatim() -> None:
    native = '("agentic AI" | agent) + workflow'
    assert build_database_query(_review({"semantic_scholar": native}), "semantic_scholar") == native


def test_openalex_and_core_use_uppercase_boolean() -> None:
    review = _review({"openalex": _OVERRIDE, "core": _OVERRIDE})
    expected = (
        '("agentic AI" OR "AI agent" OR "multi-agent system") AND '
        '("exception handling" OR "decision support" OR workflow)'
    )
    assert build_database_query(review, "openalex") == expected
    assert build_database_query(review, "core") == expected


def test_crossref_query_is_plain_keywords_without_research_question() -> None:
    review = _review()
    q = build_database_query(review, "crossref")
    assert review.research_question not in q
    for op in (" AND ", " OR ", '"', "(", ")"):
        assert op not in q
    assert "agentic AI" in q


def test_arxiv_query_is_fielded() -> None:
    q = build_database_query(_review({"arxiv": _OVERRIDE}), "arxiv")
    assert q.startswith('(all:"agentic AI" OR all:"AI agent"')
    assert ") AND (" in q and "all:workflow" in q


def test_dblp_query_uses_pipe_or_and_space_and() -> None:
    q = build_database_query(_review({"dblp": _OVERRIDE}), "dblp")
    assert q == "agentic-AI|AI-agent|multi-agent-system exception-handling|decision-support|workflow"


def test_default_query_without_overrides_uses_conceptual_structure() -> None:
    review = _review()
    cq = build_conceptual_query(review, "openalex")
    assert cq.is_structured
    assert build_database_query(review, "openalex") == cq.render()


def test_relaxed_query_is_single_or_group_in_native_syntax() -> None:
    review = _review()
    s2 = build_relaxed_database_query(review, "semantic_scholar")
    assert " | " in s2 and " + " not in s2
    oa = build_relaxed_database_query(review, "openalex")
    assert " OR " in oa and " AND " not in oa


def test_scoping_review_flag_does_not_change_query_text() -> None:
    systematic = build_database_query(_review({"openalex": _OVERRIDE}), "openalex")
    scoping = build_database_query(_review({"openalex": _OVERRIDE}, ReviewType.SCOPING), "openalex")
    assert systematic == scoping
