"""Tests for root route browser detection."""

from unittest.mock import MagicMock

from routes.root import _is_browser


def _request(*, accept: str | None = None, user_agent: str | None = None):
    request = MagicMock()
    headers = {}
    if accept is not None:
        headers["accept"] = accept
    if user_agent is not None:
        headers["user-agent"] = user_agent
    request.headers.get.side_effect = lambda key, default="": headers.get(key, default)
    return request


def test_is_browser_false_when_client_requests_json_only():
    request = _request(
        accept="application/json",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/120.0",
    )

    assert _is_browser(request) is False


def test_is_browser_true_for_direct_browser_navigation():
    request = _request(
        accept="text/html,application/xhtml+xml",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/120.0",
    )

    assert _is_browser(request) is True


def test_is_browser_true_for_browser_user_agent_without_accept_header():
    request = _request(user_agent="Mozilla/5.0 Safari/605.1.15")

    assert _is_browser(request) is True
