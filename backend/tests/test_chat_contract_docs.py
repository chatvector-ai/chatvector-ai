"""Doc-drift tests for chat API contract wording and error codes."""

from main import app
from tests.repo_layout import repo_file

_STATUS_RULE_SENTENCE = "HTTP 200 does not mean success; check `status`."


def test_api_reference_chat_contract_wording():
    text = repo_file("documentation", "content", "api-reference.md").read_text(encoding="utf-8")
    assert _STATUS_RULE_SENTENCE in text

    # Main non-streaming codes
    for code in (
        "llm_*",
        "anchor_document_excluded_by_filter",
        "no_documents_in_scope",
        "embedding_invalid_api_key",
    ):
        assert code in text, f"api-reference.md missing non-streaming code: {code!r}"

    # Stream and batch additional codes
    for code in (
        "embedding_failed",
        "embedding_mismatch",
        "stream_failed",
        "preset_not_found",
        "invalid_retrieval_config",
    ):
        assert code in text, f"api-reference.md missing additional stream/batch code: {code!r}"

    # Open set indication
    assert "not closed" in text.lower() or "can grow" in text.lower()


def test_chat_route_openapi_description_includes_status_rule():
    schema = app.openapi()
    description = schema["paths"]["/chat"]["post"]["description"]
    assert _STATUS_RULE_SENTENCE in description
