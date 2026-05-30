"""Core logic tests for version_sentry.py — happy paths + uncovered branches.

Covers: _fetch_json accept_404, _query_pypi_version not-found,
_query_github_release not-found, _check_target DRIFT/OK/INCOMPLETE/github-error,
_build_report by_status counts.
"""
from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

import version_sentry


class TestFetchJsonVersionSentry:
    def test_accept_404_returns_none(self) -> None:
        """HTTPError 404 with accept_404=True → None, not raised."""
        with patch(
            "version_sentry.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "https://pypi.org/pypi/missing/json", 404, "Not Found", {}, None
            ),
        ):
            result = version_sentry._fetch_json(
                "https://pypi.org/pypi/missing/json", accept_404=True
            )
        assert result is None

    def test_non_404_http_error_still_raises(self) -> None:
        """HTTPError 500 always re-raises (accept_404 doesn't suppress it)."""
        with patch(
            "version_sentry.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "https://pypi.org/pypi/x/json", 500, "Server Error", {}, None
            ),
        ):
            with pytest.raises(urllib.error.HTTPError):
                version_sentry._fetch_json("https://pypi.org/pypi/x/json")

    def test_json_decode_error_raises_valueerror(self) -> None:
        """Non-JSON response body → ValueError with 'non-JSON response' message."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"<html>Bad Gateway</html>"
        with patch("version_sentry.urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ValueError, match="non-JSON response"):
                version_sentry._fetch_json("https://api.github.com/repos/x/releases/latest")


class TestQueryPypiVersion:
    def test_package_not_found_raises(self) -> None:
        """404 (accept_404) → payload is None → ValueError('PyPI package not found')."""
        with patch.object(version_sentry, "_fetch_json", return_value=None):
            with pytest.raises(ValueError, match="not found"):
                version_sentry._query_pypi_version("no-such-package")


class TestQueryGithubRelease:
    def test_no_releases_raises(self) -> None:
        """404 for releases endpoint → payload is None → ValueError('No GitHub Releases')."""
        with patch.object(version_sentry, "_fetch_json", return_value=None):
            with pytest.raises(ValueError, match="No GitHub Releases"):
                version_sentry._query_github_release("WRG-11/no-releases")


class TestCheckTarget:
    def test_drift_detected(self) -> None:
        """pypi_version != gh_release → status DRIFT."""
        target = {"name": "x", "pypi_name": "x", "gh_repo": "WRG-11/x"}
        with (
            patch.object(version_sentry, "_query_pypi_version", return_value="1.0.0"),
            patch.object(version_sentry, "_query_github_release", return_value="2.0.0"),
        ):
            finding = version_sentry._check_target(target)
        assert finding["status"] == "DRIFT"
        assert "1.0.0" in (finding["error"] or "")
        assert "2.0.0" in (finding["error"] or "")

    def test_ok_when_versions_match(self) -> None:
        """Same version on PyPI and GitHub → status OK, no error."""
        target = {"name": "x", "pypi_name": "x", "gh_repo": "WRG-11/x"}
        with (
            patch.object(version_sentry, "_query_pypi_version", return_value="1.0.0"),
            patch.object(version_sentry, "_query_github_release", return_value="1.0.0"),
        ):
            finding = version_sentry._check_target(target)
        assert finding["status"] == "OK"
        assert finding["error"] is None

    def test_incomplete_when_no_pypi_name(self) -> None:
        """pypi_name=None → pypi_version stays None; gh_release populated → INCOMPLETE."""
        target = {"name": "x", "pypi_name": None, "gh_repo": "WRG-11/x"}
        with patch.object(version_sentry, "_query_github_release", return_value="1.0.0"):
            finding = version_sentry._check_target(target)
        assert finding["status"] == "INCOMPLETE"

    def test_incomplete_when_no_gh_repo(self) -> None:
        """Target with gh_repo=None → status INCOMPLETE."""
        target = {"name": "x", "pypi_name": "x", "gh_repo": None}
        with patch.object(version_sentry, "_query_pypi_version", return_value="1.0.0"):
            finding = version_sentry._check_target(target)
        assert finding["status"] == "INCOMPLETE"

    def test_github_query_error_recorded(self) -> None:
        """GitHub query failure → status ERROR with 'github' in error message."""
        target = {"name": "x", "pypi_name": "x", "gh_repo": "WRG-11/x"}
        with (
            patch.object(version_sentry, "_query_pypi_version", return_value="1.0.0"),
            patch.object(
                version_sentry,
                "_query_github_release",
                side_effect=ValueError("No GitHub Releases for: WRG-11/x"),
            ),
        ):
            finding = version_sentry._check_target(target)
        assert finding["status"] == "ERROR"
        assert "github" in (finding["error"] or "").lower()

    def test_pypi_error_recorded(self) -> None:
        """PyPI query failure → status ERROR, gh_release stays None."""
        target = {"name": "x", "pypi_name": "x", "gh_repo": "WRG-11/x"}
        with patch.object(
            version_sentry,
            "_query_pypi_version",
            side_effect=ValueError("PyPI package not found: x"),
        ):
            finding = version_sentry._check_target(target)
        assert finding["status"] == "ERROR"
        assert finding["gh_release"] is None


class TestBuildReport:
    def test_by_status_counts(self) -> None:
        """_build_report correctly tallies each status."""
        findings = [
            {"status": "OK", "name": "a"},
            {"status": "OK", "name": "b"},
            {"status": "DRIFT", "name": "c"},
            {"status": "ERROR", "name": "d"},
        ]
        report = version_sentry._build_report(findings)
        assert report["targets_checked"] == 4
        assert report["by_status"]["OK"] == 2
        assert report["by_status"]["DRIFT"] == 1
        assert report["by_status"]["ERROR"] == 1
        assert report["schema_version"] == "wrg_portfolio.version_sentry.v1"
        assert report["findings"] is findings
        assert "created_at" in report

    def test_empty_findings(self) -> None:
        """Empty findings list produces zero totals."""
        report = version_sentry._build_report([])
        assert report["targets_checked"] == 0
        assert report["by_status"] == {}
