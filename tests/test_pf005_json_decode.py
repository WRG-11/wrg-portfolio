"""R89-14b H Wave 6 PF-005 regression: non-JSON response handling.

Both ``dashboard._fetch_json`` and ``version_sentry._fetch_json``
previously bubbled ``json.JSONDecodeError`` (server returned HTML
error page, captive portal, proxy interstitial). The bubble landed
in the caller's ``except Exception`` and was logged as a generic
exception name.

After PF-005:
  * ``dashboard._fetch_json`` returns ``None`` (same code path as
    a 404 — "data unavailable").
  * ``version_sentry._fetch_json`` raises ``ValueError("non-JSON
    response ...")`` (sentry needs a recorded ERROR for exit 1).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import dashboard  # noqa: E402
import version_sentry  # noqa: E402


def _mock_resp(body: bytes) -> MagicMock:
    """Make a urlopen-style context manager that returns ``body``."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=None)
    return resp


def test_dashboard_fetch_json_returns_none_on_html_response_pf005() -> None:
    """HTML payload (e.g. captive portal) → None, not raise."""
    html_payload = b"<!DOCTYPE html><html><body>502 Bad Gateway</body></html>"
    with patch(
        "dashboard.urllib.request.urlopen",
        return_value=_mock_resp(html_payload),
    ):
        result = dashboard._fetch_json("https://pypi.org/pypi/x/json")
    assert result is None


def test_dashboard_fetch_json_returns_none_on_invalid_utf8_pf005() -> None:
    """Invalid UTF-8 bytes → None (UnicodeDecodeError caught)."""
    # 0xFF is invalid as a start byte in UTF-8.
    with patch(
        "dashboard.urllib.request.urlopen",
        return_value=_mock_resp(b"\xff\xfe garbage"),
    ):
        result = dashboard._fetch_json("https://pypi.org/pypi/x/json")
    assert result is None


def test_version_sentry_fetch_json_raises_on_html_response_pf005() -> None:
    """version_sentry path: HTML payload → ValueError(non-JSON ...)."""
    html_payload = b"<!DOCTYPE html><html><body>502</body></html>"
    with patch(
        "version_sentry.urllib.request.urlopen",
        return_value=_mock_resp(html_payload),
    ):
        with pytest.raises(ValueError, match="non-JSON response"):
            version_sentry._fetch_json("https://pypi.org/pypi/x/json")
