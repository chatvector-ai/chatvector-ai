"""Poll and print document status information."""

from __future__ import annotations

import os

from chatvector import ChatVectorClient


def main() -> None:
    """Fetch and display the current status for a document."""
    base_url = os.environ.get("CHATVECTOR_BASE_URL", "http://localhost:8000")
    api_key = os.environ.get("CHATVECTOR_API_KEY")
    document_id = os.environ["CHATVECTOR_DOCUMENT_ID"]

    with ChatVectorClient(base_url=base_url, api_key=api_key) as client:
        status = client.get_status(document_id)

    print(f"document_id={status.document_id}")
    print(f"status={status.status}")
    print(f"queue_position={status.queue_position}")
    print(f"chunks={status.chunks}")
    print(f"error={status.error}")


if __name__ == "__main__":
    main()
