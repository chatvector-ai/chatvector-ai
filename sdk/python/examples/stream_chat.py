"""Stream a ChatVector answer token-by-token and print citations."""

from __future__ import annotations

import os

from chatvector import ChatVectorClient


def main() -> None:
    """Stream a chat answer and print tokens plus final citations."""
    base_url = os.environ.get("CHATVECTOR_BASE_URL", "http://localhost:8000")
    api_key = os.environ.get("CHATVECTOR_API_KEY")
    document_id = os.environ["CHATVECTOR_DOCUMENT_ID"]
    session_id = os.environ.get("CHATVECTOR_SESSION_ID")

    with ChatVectorClient(base_url=base_url, api_key=api_key) as client:
        for event in client.stream_chat(
            question="Summarize this document.",
            doc_id=document_id,
            session_id=session_id,
            timeout=60,
        ):
            if event.type == "token":
                print(event.content, end="", flush=True)
            elif event.type == "complete":
                print()
                print(f"session_id={event.session_id} model={event.model}")
                for source in event.sources:
                    print(
                        f"- {source.file_name} "
                        f"(page={source.page_number}, score={source.score})"
                    )


if __name__ == "__main__":
    main()
