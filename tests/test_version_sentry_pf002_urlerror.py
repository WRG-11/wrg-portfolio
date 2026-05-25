"""R89-14b H Wave 6 PF-002 regression: version_sentry.py URLError handling.

Sister of dashboard.py PF-001. Before PF-002 the helper raised raw
``URLError`` to ``_check_target``'s ``except Exception`` where it was
indistinguishable from any other programming bug in the same try
block.

After PF-002 the helper raises ``ValueError`` with a "network
unavailable" message so the exception type itself carries semantic
meaning.
"""
from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

import version_sentry  # noqa: E402  -- via tests/conftest.py sys.path


def test_fetch_json_raises_valueerror_on_urlerror_pf002() -> None:
    """URLError → ValueError with `network unavailable` message."""
    with patch(
        "version_sentry.urllib.request.urlopen",
        side_effect=urllib.error.URLError("name resolution failed"),
    ):
        with pytest.raises(ValueError, match="network unavailable"):
            version_sentry._fetch_json("https://pypi.org/pypi/x/json")


def test_check_target_records_network_error_pf002() -> None:
    """End-to-end: _check_target catches the new ValueError and
    records a structured ERROR finding instead of a generic
    `URLError` string."""
    target = {"name": "x", "pypi_name": "x", "gh_repo": "WRG-11/x"}
    with patch(
        "version_sentry.urllib.request.urlopen",
        side_effect=urllib.error.URLError("conn refused"),
    ):
        finding = version_sentry._check_target(target)
    assert finding["status"] == "ERROR"
    assert "ValueError" in (finding["error"] or "")
    assert "network unavailable" in (finding["error"] or "").lower()
