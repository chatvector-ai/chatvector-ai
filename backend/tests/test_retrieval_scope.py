import pytest

from services.retrieval_service import (
    DEFAULT_RETRIEVAL_SCOPE,
    InvalidRetrievalScopeError,
    RetrievalScope,
    assert_tenant_isolation,
    filter_doc_ids_for_tenant,
    parse_retrieval_scope,
    resolve_scoped_doc_ids,
)


class TestParseRetrievalScope:
    def test_defaults_to_session(self):
        assert parse_retrieval_scope(None) == DEFAULT_RETRIEVAL_SCOPE
        assert parse_retrieval_scope(None) == RetrievalScope.SESSION

    def test_accepts_valid_scopes(self):
        assert parse_retrieval_scope("session") == RetrievalScope.SESSION
        assert parse_retrieval_scope("tenant") == RetrievalScope.TENANT
        assert parse_retrieval_scope("  TENANT  ") == RetrievalScope.TENANT

    def test_rejects_invalid_scope(self):
        with pytest.raises(InvalidRetrievalScopeError, match="Invalid retrieval scope"):
            parse_retrieval_scope("global")
        with pytest.raises(InvalidRetrievalScopeError):
            parse_retrieval_scope("")


class TestResolveScopedDocIds:
    def test_session_scope_uses_requested_when_session_empty(self):
        result = resolve_scoped_doc_ids(
            RetrievalScope.SESSION,
            requested_doc_ids=["doc-a", "doc-b"],
            session_doc_ids=[],
        )
        assert result == ["doc-a", "doc-b"]

    def test_session_scope_intersects_with_session_documents(self):
        result = resolve_scoped_doc_ids(
            RetrievalScope.SESSION,
            requested_doc_ids=["doc-a", "doc-c"],
            session_doc_ids=["doc-a", "doc-b"],
        )
        assert result == ["doc-a"]

    def test_session_scope_returns_session_docs_when_no_request(self):
        result = resolve_scoped_doc_ids(
            RetrievalScope.SESSION,
            requested_doc_ids=[],
            session_doc_ids=["doc-a", "doc-b"],
        )
        assert result == ["doc-a", "doc-b"]

    def test_tenant_scope_returns_all_tenant_documents(self):
        result = resolve_scoped_doc_ids(
            RetrievalScope.TENANT,
            requested_doc_ids=["doc-other"],
            tenant_doc_ids=["doc-x", "doc-y"],
        )
        assert result == ["doc-x", "doc-y"]

    def test_tenant_scope_ignores_requested_when_tenant_registry_present(self):
        result = resolve_scoped_doc_ids(
            RetrievalScope.TENANT,
            requested_doc_ids=["doc-x", "doc-foreign"],
            tenant_doc_ids=["doc-x", "doc-y"],
        )
        assert result == ["doc-x", "doc-y"]

    def test_tenant_scope_falls_back_to_requested_without_registry(self):
        result = resolve_scoped_doc_ids(
            RetrievalScope.TENANT,
            requested_doc_ids=["doc-a"],
            tenant_doc_ids=[],
        )
        assert result == ["doc-a"]


class TestTenantIsolation:
    def test_filter_doc_ids_for_tenant_removes_foreign_docs(self):
        filtered = filter_doc_ids_for_tenant(
            ["doc-a", "doc-b", "doc-c"],
            tenant_doc_ids=["doc-a", "doc-c"],
            tenant_id="tenant-1",
        )
        assert filtered == ["doc-a", "doc-c"]

    def test_filter_doc_ids_skips_when_no_tenant(self):
        doc_ids = ["doc-a", "doc-b"]
        assert filter_doc_ids_for_tenant(doc_ids, ["doc-a"], tenant_id=None) == doc_ids

    def test_assert_tenant_isolation_raises_on_leak(self):
        with pytest.raises(ValueError, match="not accessible for tenant"):
            assert_tenant_isolation(
                ["doc-a", "doc-foreign"],
                tenant_doc_ids=["doc-a"],
                tenant_id="tenant-1",
            )

    def test_assert_tenant_isolation_passes_for_valid_docs(self):
        assert_tenant_isolation(
            ["doc-a"],
            tenant_doc_ids=["doc-a", "doc-b"],
            tenant_id="tenant-1",
        )
