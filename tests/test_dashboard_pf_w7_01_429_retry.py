"""R89-16b H PF-W7-01 regression guard — _fetch_json 429 retry honours
Retry-After + fresh Request."""
from __future__ import annotations

import io
import sys
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

# Load scripts/dashboard.py as a module (the script-style layout has no
# __init__.py).
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dashboard  # noqa: E402


def _make_http_error_429(retry_after: str | None = "3") -> urllib.error.HTTPError:
    """Build an HTTPError with code=429 and an optional Retry-After header."""
    hdrs = Message()
    if retry_after is not None:
        hdrs["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        url="https://example.invalid/x",
        code=429,
        msg="Too Many Requests",
        hdrs=hdrs,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )


class FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "FakeResp":
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class PFW701RetryAfterHonored(unittest.TestCase):
    """R89-16b H PF-W7-01: 429 retry now (a) honours server-provided
    Retry-After header (was: ignored — fixed 7s), and (b) builds a
    fresh Request on retry (defensive against urllib internal state
    mutation between CPython minor versions)."""

    def test_retry_after_header_used_when_present(self) -> None:
        first = _make_http_error_429(retry_after="2")
        urlopen_calls: list[object] = []
        sleep_calls: list[float] = []

        def _fake_urlopen(req, timeout):  # noqa: ANN001
            urlopen_calls.append(req)
            if len(urlopen_calls) == 1:
                raise first
            return FakeResp(b'{"ok": true}')

        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen), \
             mock.patch.object(dashboard.time, "sleep", side_effect=sleep_calls.append):
            result = dashboard._fetch_json("https://x.invalid/y", retry_429=True)

        self.assertEqual(result, {"ok": True})
        # Exactly one sleep, and it MUST be the server-supplied 2s
        # (not the legacy fixed 7s).
        self.assertEqual(len(sleep_calls), 1, sleep_calls)
        self.assertEqual(sleep_calls[0], 2)
        # Two urlopen calls — original + retry.
        self.assertEqual(len(urlopen_calls), 2)
        # Retry MUST use a fresh Request instance (different id), not
        # the same one the first urlopen consumed.
        self.assertIsNot(urlopen_calls[0], urlopen_calls[1])

    def test_falls_back_to_fixed_backoff_when_no_retry_after(self) -> None:
        first = _make_http_error_429(retry_after=None)
        sleep_calls: list[float] = []

        urlopen_calls = [0]

        def _fake_urlopen(req, timeout):  # noqa: ANN001
            urlopen_calls[0] += 1
            if urlopen_calls[0] == 1:
                raise first
            return FakeResp(b'{"ok": true}')

        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen), \
             mock.patch.object(dashboard.time, "sleep", side_effect=sleep_calls.append):
            result = dashboard._fetch_json("https://x.invalid/y", retry_429=True)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(sleep_calls, [dashboard.RATE_LIMIT_BACKOFF_SECONDS])

    def test_retry_after_capped_at_60s(self) -> None:
        first = _make_http_error_429(retry_after="9999")
        sleep_calls: list[float] = []
        urlopen_calls = [0]

        def _fake_urlopen(req, timeout):  # noqa: ANN001
            urlopen_calls[0] += 1
            if urlopen_calls[0] == 1:
                raise first
            return FakeResp(b'{"ok": true}')

        with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen), \
             mock.patch.object(dashboard.time, "sleep", side_effect=sleep_calls.append):
            dashboard._fetch_json("https://x.invalid/y", retry_429=True)

        # Capped at 60 — never trust the server to wait forever.
        self.assertLessEqual(sleep_calls[0], 60)
        self.assertGreaterEqual(sleep_calls[0], 1)


if __name__ == "__main__":
    unittest.main()
