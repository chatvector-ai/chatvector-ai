"""Upload a document, wait for ingestion, and ask a question."""

from __future__ import annotations

import os

from chatvector import ChatVectorClient


def main() -> None:
    """Run a simple upload -> wait -> chat workflow."""
    base_url = os.environ.get("CHATVECTOR_BASE_URL", "http://localhost:8000")
    api_key = os.environ.get("CHATVECTOR_API_KEY")
    document_path = os.environ.get("CHATVECTOR_DOCUMENT_PATH", "example.pdf")

    with ChatVectorClient(base_url=base_url, api_key=api_key) as client:
        upload = client.upload_document(document_path)
        print(f"Uploaded {document_path} as {upload.document_id} ({upload.status})")

        ready = client.wait_for_ready(upload.document_id, timeout=90, interval=3)
        print(f"Document is now {ready.status}")

        answer = client.chat(
            question="Give me a concise summary of this document.",
            doc_id=upload.document_id,
            match_count=3,
        )

    print(answer.answer)
    for source in answer.sources:
        print(
            f"- file={source.file_name!r} page={source.page_number} chunk={source.chunk_index}"
        )


if __name__ == "__main__":
    main()
