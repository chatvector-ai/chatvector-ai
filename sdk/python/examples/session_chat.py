"""Demonstrate session management and scoped chat with the ChatVector SDK."""

from __future__ import annotations

import os

from chatvector import ChatVectorClient


def main() -> None:
    """Create a session, chat against a document, then query tenant-wide."""
    base_url = os.environ.get("CHATVECTOR_BASE_URL", "http://localhost:8000")
    api_key = os.environ.get("CHATVECTOR_API_KEY")
    document_id = os.environ["CHATVECTOR_DOCUMENT_ID"]

    with ChatVectorClient(base_url=base_url, api_key=api_key) as client:
        session = client.create_session()
        print(f"Created session {session.id}")

        scoped = client.chat(
            question="Summarize this document.",
            doc_id=document_id,
            session_id=session.id,
        )
        print(scoped.answer)

        tenant_wide = client.chat(
            question="What do we know across all documents?",
            doc_id=document_id,
            session_id=session.id,
            scope="tenant",
        )
        print(tenant_wide.answer)

        updated = client.get_session(session.id)
        print(f"Session documents: {updated.document_ids}")

        client.delete_session(session.id)
        print(f"Deleted session {session.id}")


if __name__ == "__main__":
    main()
