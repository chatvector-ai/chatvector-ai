"""SDK support for replacing a document in place (``replace_document_id``)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from chatvector import (
    AsyncChatVectorClient,
    ChatVectorAPIError,
    ChatVectorClient,
    DocumentResponse,
    DocumentStatus,
)
from chatvector.models import DocumentSummary

REPLACE_ID = "11111111-2222-3333-4444-555555555555"


def _accepted_replacement(method: str = "POST", url: str = "https://api.chatvector.test/ingest"):
    return httpx.Response(
        202,
        json={
            "message": "Accepted",
            "document_id": REPLACE_ID,
            "status": "completed",
            "status_detail": "replacement_in_progress",
            "queue_position": 1,
            "status_endpoint": f"/documents/{REPLACE_ID}/status",
        },
        request=httpx.Request(method, url),
    )


class ModelTests(unittest.TestCase):
    def test_document_response_parses_status_detail(self) -> None:
        response = DocumentResponse.from_dict(
            {
                "document_id": REPLACE_ID,
                "status": "completed",
                "status_detail": "replacement_in_progress",
            }
        )
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.status_detail, "replacement_in_progress")
        self.assertEqual(response.to_dict()["status_detail"], "replacement_in_progress")

    def test_status_models_omit_status_detail_when_absent(self) -> None:
        response = DocumentResponse.from_dict({"document_id": "d", "status": "queued"})
        status = DocumentStatus.from_dict({"document_id": "d", "status": "queued"})
        summary = DocumentSummary.from_dict(
            {"document_id": "d", "file_name": "f", "status": "queued"}
        )
        for model in (response, status, summary):
            self.assertIsNone(model.status_detail)
            self.assertNotIn("status_detail", model.to_dict())

    def test_status_and_summary_parse_status_detail(self) -> None:
        status = DocumentStatus.from_dict(
            {"document_id": "d", "status": "completed", "status_detail": "replacement_failed"}
        )
        summary = DocumentSummary.from_dict(
            {
                "document_id": "d",
                "file_name": "f",
                "status": "completed",
                "status_detail": "replacement_in_progress",
            }
        )
        self.assertEqual(status.status_detail, "replacement_failed")
        self.assertEqual(status.to_dict()["status_detail"], "replacement_failed")
        self.assertEqual(summary.status_detail, "replacement_in_progress")
        self.assertEqual(summary.to_dict()["status_detail"], "replacement_in_progress")

    def test_document_status_parses_file_name_when_present(self) -> None:
        status = DocumentStatus.from_dict(
            {"document_id": "d", "status": "completed", "file_name": "notes.txt"}
        )
        self.assertEqual(status.file_name, "notes.txt")
        self.assertEqual(status.to_dict()["file_name"], "notes.txt")
        self.assertEqual(status.status, "completed")

    def test_document_status_omits_file_name_when_absent(self) -> None:
        status = DocumentStatus.from_dict({"document_id": "d", "status": "queued"})
        self.assertIsNone(status.file_name)
        self.assertNotIn("file_name", status.to_dict())
        self.assertEqual(status.to_dict()["document_id"], "d")
        self.assertEqual(status.to_dict()["status"], "queued")


class SyncClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = ChatVectorClient("https://api.chatvector.test", api_key="token")
        self.addCleanup(self.client.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file_path = Path(self.tmp.name) / "guide-v2.pdf"
        self.file_path.write_bytes(b"%PDF-1.4")

    def test_upload_sends_replace_document_id_form_field(self) -> None:
        captured: dict[str, object] = {}

        def fake_request(method, url, **kwargs):
            captured["url"] = url
            captured["data"] = kwargs.get("data")
            return _accepted_replacement(method, f"https://api.chatvector.test/{url}")

        with patch.object(self.client._client, "request", side_effect=fake_request):
            response = self.client.upload_document(
                str(self.file_path), replace_document_id=f"  {REPLACE_ID} "
            )

        self.assertEqual(captured["data"], {"replace_document_id": REPLACE_ID})
        self.assertEqual(response.document_id, REPLACE_ID)
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.status_detail, "replacement_in_progress")

    def test_upload_without_replace_sends_no_form_data(self) -> None:
        captured: dict[str, object] = {}

        def fake_request(method, url, **kwargs):
            captured["kwargs"] = kwargs
            return httpx.Response(
                202,
                json={"document_id": "new-doc", "status": "queued"},
                request=httpx.Request(method, f"https://api.chatvector.test/{url}"),
            )

        with patch.object(self.client._client, "request", side_effect=fake_request):
            response = self.client.upload_document(str(self.file_path))

        self.assertNotIn("data", captured["kwargs"])
        self.assertIsNone(response.status_detail)

    def test_upload_rejects_blank_replace_document_id(self) -> None:
        with patch.object(self.client._client, "request") as mock_request:
            with self.assertRaises(ValueError):
                self.client.upload_document(str(self.file_path), replace_document_id="  ")
        mock_request.assert_not_called()

    def test_upload_maps_409_conflict_to_api_error(self) -> None:
        conflict = httpx.Response(
            409,
            json={
                "detail": {
                    "code": "replacement_in_progress",
                    "message": "A replacement for this document is already in progress.",
                }
            },
            request=httpx.Request("POST", "https://api.chatvector.test/ingest"),
        )
        with patch.object(self.client._client, "request", side_effect=[conflict]):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                self.client.upload_document(
                    str(self.file_path), replace_document_id=REPLACE_ID
                )
        self.assertEqual(exc_info.exception.status_code, 409)

    def test_wait_for_ready_keeps_polling_while_replacement_in_progress(self) -> None:
        in_progress = DocumentStatus(
            document_id=REPLACE_ID,
            status="completed",
            status_detail="replacement_in_progress",
        )
        done = DocumentStatus(document_id=REPLACE_ID, status="completed")

        with (
            patch.object(
                self.client, "get_status", side_effect=[in_progress, in_progress, done]
            ) as mock_status,
            patch("chatvector.client.time.sleep", return_value=None),
        ):
            result = self.client.wait_for_ready(REPLACE_ID, timeout=10, interval=1)

        self.assertIsNone(result.status_detail)
        self.assertEqual(mock_status.call_count, 3)

    def test_wait_for_ready_raises_when_replacement_failed(self) -> None:
        failed = DocumentStatus(
            document_id=REPLACE_ID,
            status="completed",
            status_detail="replacement_failed",
            error={"message": "Embedding provider unreachable."},
        )
        with patch.object(self.client, "get_status", return_value=failed):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                self.client.wait_for_ready(REPLACE_ID, timeout=10, interval=1)

        message = str(exc_info.exception)
        self.assertIn("replacement failed", message)
        self.assertIn("Embedding provider unreachable.", message)

    def test_wait_for_ready_still_returns_plain_completed_documents(self) -> None:
        completed = DocumentStatus(document_id="doc-1", status="completed")
        with patch.object(self.client, "get_status", return_value=completed):
            result = self.client.wait_for_ready("doc-1", timeout=10, interval=1)
        self.assertEqual(result.status, "completed")

    def test_wait_for_ready_still_reports_plain_failed_documents(self) -> None:
        failed = DocumentStatus(
            document_id="doc-1", status="failed", error={"message": "bad pdf"}
        )
        with patch.object(self.client, "get_status", return_value=failed):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                self.client.wait_for_ready("doc-1", timeout=10, interval=1)
        self.assertIn("processing failed", str(exc_info.exception))


class AsyncClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = AsyncChatVectorClient("https://api.chatvector.test", api_key="token")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file_path = Path(self.tmp.name) / "guide-v2.pdf"
        self.file_path.write_bytes(b"%PDF-1.4")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_upload_sends_replace_document_id_form_field(self) -> None:
        mock_request = AsyncMock(return_value=_accepted_replacement())
        with patch.object(self.client._client, "request", new=mock_request):
            response = await self.client.upload_document(
                str(self.file_path), replace_document_id=REPLACE_ID
            )

        self.assertEqual(
            mock_request.await_args.kwargs["data"], {"replace_document_id": REPLACE_ID}
        )
        self.assertEqual(response.status_detail, "replacement_in_progress")

    async def test_upload_without_replace_sends_no_form_data(self) -> None:
        ok = httpx.Response(
            202,
            json={"document_id": "new-doc", "status": "queued"},
            request=httpx.Request("POST", "https://api.chatvector.test/ingest"),
        )
        mock_request = AsyncMock(return_value=ok)
        with patch.object(self.client._client, "request", new=mock_request):
            await self.client.upload_document(str(self.file_path))

        self.assertNotIn("data", mock_request.await_args.kwargs)

    async def test_upload_rejects_blank_replace_document_id(self) -> None:
        with self.assertRaises(ValueError):
            await self.client.upload_document(str(self.file_path), replace_document_id="")

    async def test_wait_for_ready_keeps_polling_while_replacement_in_progress(self) -> None:
        in_progress = DocumentStatus(
            document_id=REPLACE_ID,
            status="completed",
            status_detail="replacement_in_progress",
        )
        done = DocumentStatus(document_id=REPLACE_ID, status="completed")
        get_status = AsyncMock(side_effect=[in_progress, done])

        with (
            patch.object(self.client, "get_status", new=get_status),
            patch("chatvector.async_client.asyncio.sleep", new=AsyncMock()),
        ):
            result = await self.client.wait_for_ready(REPLACE_ID, timeout=10, interval=1)

        self.assertIsNone(result.status_detail)
        self.assertEqual(get_status.await_count, 2)

    async def test_wait_for_ready_raises_when_replacement_failed(self) -> None:
        failed = DocumentStatus(
            document_id=REPLACE_ID,
            status="completed",
            status_detail="replacement_failed",
            error={"message": "Embedding provider unreachable."},
        )
        with patch.object(self.client, "get_status", new=AsyncMock(return_value=failed)):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                await self.client.wait_for_ready(REPLACE_ID, timeout=10, interval=1)

        self.assertIn("replacement failed", str(exc_info.exception))


if __name__ == "__main__":
    unittest.main()
