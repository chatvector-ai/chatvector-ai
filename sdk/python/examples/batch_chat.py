"""Run multiple ChatVector questions in a single request."""

from __future__ import annotations

import os

from chatvector import BatchChatQuery, ChatVectorClient


def main() -> None:
    """Submit several batch chat queries and print the results."""
    base_url = os.environ.get("CHATVECTOR_BASE_URL", "http://localhost:8000")
    api_key = os.environ.get("CHATVECTOR_API_KEY")
    document_id = os.environ["CHATVECTOR_DOCUMENT_ID"]

    queries = [
        BatchChatQuery(
            question="Summarize the document.",
            doc_ids=[document_id],
            match_count=3,
        ),
        BatchChatQuery(
            question="What are the key risks mentioned?",
            doc_ids=[document_id],
            match_count=4,
        ),
    ]

    with ChatVectorClient(base_url=base_url, api_key=api_key) as client:
        batch = client.batch_chat(queries)

    print(
        f"count={batch.count} success={batch.success_count} failure={batch.failure_count}"
    )
    for result in batch.results:
        print(f"[{result.status}] {result.question}")
        if result.answer:
            print(result.answer)
        if result.error:
            print(result.error)


if __name__ == "__main__":
    main()
