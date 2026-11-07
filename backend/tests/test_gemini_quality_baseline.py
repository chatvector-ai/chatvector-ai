"""The checked-in Gemini baseline report names this run and its sections.

The test reads the file. It does not import a provider client or call the
network.
"""

import hashlib
import re
from pathlib import Path

BRINEWICK = Path(__file__).resolve().parents[1] / "eval" / "brinewick"
REPORT = BRINEWICK / "gemini-quality-baseline.md"
QUESTIONS = BRINEWICK / "questions.json"


def _folded(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


_REQUIRED_HEADINGS = (
    "## Configuration",
    "## Retrieval",
    "## Answers",
    "## Conversation",
    "## Latency",
    "## Integration support is not quality validation",
)

_RANK_TOKENS = ("MRR", "recall@5", "nDCG@5", "recall@10", "nDCG@10")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading) :]
    next_heading = rest.find("\n## ")
    if next_heading == -1:
        return rest
    return rest[:next_heading]


def test_report_contains_required_sections_and_reference_configuration():
    text = REPORT.read_text(encoding="utf-8")
    folded = _folded(text)

    for heading in _REQUIRED_HEADINGS:
        assert heading in text

    configuration = _section(text, "## Configuration")
    assert "`gemini-2.5-flash`" in configuration
    assert "`models/gemini-embedding-001`" in configuration
    assert "`gemini`" in configuration
    assert "`default`" in configuration
    assert "PROMPT_PERSONA" in configuration
    assert "`fixed`" in configuration
    assert "`1000`" in configuration
    assert "`200`" in configuration
    assert "hybrid" in configuration.lower()
    assert "reranking" in configuration.lower()
    assert "match_count" in configuration
    assert "brinewick-transit-cooperative" in configuration
    corpus_hash = hashlib.sha256(QUESTIONS.read_bytes()).hexdigest()
    assert corpus_hash in configuration

    retrieval = _section(text, "## Retrieval")
    for token in _RANK_TOKENS:
        assert token in retrieval
    assert "packed-context presence fraction" in retrieval

    answers = _section(text, "## Answers")
    for token in ("Completeness", "Groundedness", "Citation support", "Refusal correctness"):
        assert token in answers

    conversation = _section(text, "## Conversation")
    assert "follow-up" in conversation.lower()
    assert "passed" in conversation.lower()
    assert "failed scenario" in conversation.lower()

    latency = _section(text, "## Latency")
    assert "timing_ms" in latency
    assert "answer_latency_ms" in latency
    assert "generate_answer" in latency

    assert "engineering baseline" in folded
    assert "not a public benchmark" in folded
    assert "not a provider certification matrix" in folded
    assert "quality reference" in folded
    assert "initializing, embedding, generating" in folded
    assert "streaming, timing out, and returning valid output" in folded
    assert "does not include a certification matrix" in folded
    assert "does not record a local or ollama quality run" in folded


def test_rank_metrics_are_not_published_without_packed_context_presence():
    text = REPORT.read_text(encoding="utf-8")
    retrieval = _section(text, "## Retrieval")
    has_rank = any(token in retrieval for token in _RANK_TOKENS)
    assert has_rank
    assert "packed-context presence fraction" in retrieval


def test_report_does_not_claim_a_public_benchmark_or_certify_providers():
    folded = _folded(REPORT.read_text(encoding="utf-8"))
    assert "this file is an engineering baseline" in folded
    assert "not a public benchmark" in folded
    assert "no table certifies other providers" in folded
    assert "this is a public benchmark" not in folded
    assert "not a provider certification matrix" in folded
