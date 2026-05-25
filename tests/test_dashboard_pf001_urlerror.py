"""R89-14b H Wave 6 PF-001 regression: dashboard.py URLError handling.

Before PF-001 the ``_fetch_json`` helper caught only ``HTTPError`` so
DNS / connection-refused / TLS failures bubbled out as bare
``URLError`` and forced every caller in ``_collect_target`` to
``except Exception`` (over-broad — silently swallowed programming
bugs too).

After PF-001 the helper returns ``None`` on URLError so callers can
recognise "data unavailable" without catch-all heroics.
"""
from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

import dashboard  # noqa: E402  -- via tests/conftest.py sys.path injection


def test_fetch_json_returns_none_on_urlerror_pf001() -> None:
    """Primary path: DNS / conn-refused → None (not raised)."""
    with patch(
        "dashboard.urllib.request.urlopen",
        side_effect=urllib.error.URLError("Temporary failure in name resolution"),
    ):
        result = dashboard._fetch_json("https://pypi.org/pypi/missing/json")
    assert result is None, (
        "PF-001: URLError must return None, not bubble. "
        "Old behavior: caller's `except Exception` swallowed it."
    )


def test_fetch_json_returns_none_on_urlerror_retry_path_pf001() -> None:
    """Retry path (HTTP 429 retry): URLError on retry → None too."""
    call_count = {"n": 0}

    def _side_effect(req, timeout=15):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise urllib.error.HTTPError(
                "https://example.invalid", 429, "Too Many Requests", {}, None
            )
        raise urllib.error.URLError("conn refused on retry")

    with patch("dashboard.urllib.request.urlopen", side_effect=_side_effect):
        with patch("dashboard.time.sleep"):
            result = dashboard._fetch_json(
                "https://pypistats.org/api/packages/x/recent", retry_429=True
            )
    assert result is None
    assert call_count["n"] == 2, "retry path must actually attempt the retry"


def test_fetch_json_still_raises_non_url_errors() -> None:
    """PF-001 must NOT over-catch — programming bugs still bubble."""
    with patch(
        "dashboard.urllib.request.urlopen",
        side_effect=ValueError("intentional programmer bug"),
    ):
        with pytest.raises(ValueError):
            dashboard._fetch_json("https://example.invalid/")
