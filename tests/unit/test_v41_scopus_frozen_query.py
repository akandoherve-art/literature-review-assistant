"""Regression guard for the frozen Scopus V4.1 doctoral search strategy."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from src.models import ReviewConfig
from src.search.strategy import build_database_query


FIXTURE = Path("tests/fixtures/v41/scopus_v41.yaml")

EXPECTED_SHA256 = "4eadf13ccee5480c75103ed9000c7b101b69e6bdfa56fac4bcc34f360a28ee5b"


def _fixture() -> dict:
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def _query() -> str:
    return _fixture()["query"]


def _minimal_config() -> ReviewConfig:
    payload = _fixture()["review_config"]

    if hasattr(ReviewConfig, "model_validate"):
        return ReviewConfig.model_validate(payload)

    return ReviewConfig.parse_obj(payload)


def test_v41_fixture_metadata_is_frozen():
    data = _fixture()

    assert data["version"] == "V4.1"
    assert data["database"] == "scopus"
    assert data["validation"]["population"] == 536
    assert data["validation"]["sentinels_recovered"] == "7/7"


def test_v41_scopus_fingerprint_is_frozen():
    query = _query()

    actual_sha256 = hashlib.sha256(
        query.encode("utf-8")
    ).hexdigest()

    assert actual_sha256 == EXPECTED_SHA256
    assert actual_sha256 == _fixture()["sha256"]


def test_v41_scopus_override_is_loaded_verbatim():
    config = _minimal_config()
    executed = build_database_query(config, "scopus")

    assert executed == _query()


def test_v41_scopus_scientific_terms_are_preserved():
    query = _query()

    required = [
        '"agentic system"',
        '"agentic systems"',
        '"agentic AI"',
        '"AI agent"',
        '"AI agents"',
        '"autonomous agent"',
        '"autonomous agents"',
        '"intelligent agent"',
        '"intelligent agents"',
        '"software agent"',
        '"software agents"',
        '"multi-agent system"',
        '"multi-agent systems"',
        '"multiagent system"',
        '"multiagent systems"',
        '"agent-oriented system"',
        '"agent-oriented systems"',
        '"agent-based system"',
        '"agent-based systems"',
        '"agent based system"',
        '"agent based systems"',
        '"operational exception"',
        '"operational exceptions"',
        '"process exception"',
        '"process exceptions"',
        '"workflow exception"',
        '"workflow exceptions"',
        '"exception management"',
        '"exception handling"',
        '"exception detection"',
        '"exception resolution"',
        '"exception recovery"',
        '"exception escalation"',
        '"anomaly handling"',
        '"escalation management"',
        '"operational decision"',
        '"operational decision-making"',
        '"operational decision making"',
        '"operational decision support"',
        '"process adaptation"',
        '"adaptive workflow"',
        '"dynamic workflow"',
        '"exception monitoring"',
        '"business process management"',
    ]

    for term in required:
        assert term in query, f"Terme V4.1 manquant : {term}"


def test_v41_scopus_generic_terms_remain_excluded():
    query = _query()

    assert '"decision support"' not in query
    assert '"business process"' not in query


def test_v41_scopus_structure_and_period_are_frozen():
    query = _query()

    assert query.count("TITLE-ABS-KEY(") == 2
    assert "PUBYEAR > 1999" in query
    assert "PUBYEAR < 2027" in query
    assert "NOT DOCTYPE(re)" not in query
