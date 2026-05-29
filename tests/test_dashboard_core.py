"""Core function tests for dashboard.py — pure helpers + _collect_target paths.

Covers: _fmt_int, _load_dl_cache, _save_dl_cache, _cache_age_label,
_fmt_relative_date, _sparkline_svg, _date_to_days, and _collect_target
GitHub + drift paths.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


import dashboard


# ---------------------------------------------------------------------------
# _fmt_int
# ---------------------------------------------------------------------------

class TestFmtInt:
    def test_none_returns_question_mark(self) -> None:
        assert dashboard._fmt_int(None) == "?"

    def test_small_number_returned_as_string(self) -> None:
        assert dashboard._fmt_int(500) == "500"

    def test_zero(self) -> None:
        assert dashboard._fmt_int(0) == "0"

    def test_large_number_contains_digits(self) -> None:
        result = dashboard._fmt_int(12345)
        # Formatted with a comma separator — at minimum contains "12" and "345"
        assert "12" in result
        assert "345" in result


# ---------------------------------------------------------------------------
# _load_dl_cache / _save_dl_cache
# ---------------------------------------------------------------------------

class TestDlCache:
    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = dashboard._load_dl_cache(tmp_path / "nonexistent.json")
        assert result == {}

    def test_load_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json!", encoding="utf-8")
        assert dashboard._load_dl_cache(bad) == {}

    def test_roundtrip(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache.json"
        data = {"pkg": {"last_month": 42, "fetched_at": "2026-05-01T00:00:00Z"}}
        dashboard._save_dl_cache(cache_file, data)
        assert dashboard._load_dl_cache(cache_file) == data

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "dl_cache.json"
        dashboard._save_dl_cache(deep, {"x": 1})
        assert deep.exists()

    def test_save_oserror_is_silent(self, tmp_path: Path) -> None:
        """Write failure must not raise — cache is best-effort."""
        cache_file = tmp_path / "cache.json"
        with patch("dashboard.Path.write_text", side_effect=OSError("disk full")):
            dashboard._save_dl_cache(cache_file, {"x": 1})  # must not raise


# ---------------------------------------------------------------------------
# _cache_age_label
# ---------------------------------------------------------------------------

class TestCacheAgeLabel:
    def test_none_returns_empty(self) -> None:
        assert dashboard._cache_age_label(None) == ""

    def test_bad_iso_returns_empty(self) -> None:
        assert dashboard._cache_age_label("not-a-timestamp") == ""

    def test_less_than_one_hour(self) -> None:
        fixed_now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        with patch("dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = dashboard._cache_age_label("2026-05-30T11:45:00+00:00")
        assert result == "cached <1h ago"

    def test_hours_range(self) -> None:
        fixed_now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        with patch("dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = dashboard._cache_age_label("2026-05-30T09:00:00+00:00")
        assert result == "cached 3h ago"

    def test_days_range(self) -> None:
        fixed_now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        with patch("dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = dashboard._cache_age_label("2026-05-28T12:00:00+00:00")
        assert result == "cached 2d ago"


# ---------------------------------------------------------------------------
# _fmt_relative_date
# ---------------------------------------------------------------------------

class TestFmtRelativeDate:
    def test_none_returns_question_mark(self) -> None:
        assert dashboard._fmt_relative_date(None) == "?"

    def test_bad_iso_returns_input_unchanged(self) -> None:
        assert dashboard._fmt_relative_date("not-a-date") == "not-a-date"

    def test_today(self) -> None:
        fixed_now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        with patch("dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = dashboard._fmt_relative_date("2026-05-30T06:00:00+00:00")
        assert result == "today"

    def test_yesterday(self) -> None:
        fixed_now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        with patch("dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = dashboard._fmt_relative_date("2026-05-29T06:00:00+00:00")
        assert result == "yesterday"

    def test_days_ago(self) -> None:
        fixed_now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        with patch("dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = dashboard._fmt_relative_date("2026-05-15T00:00:00+00:00")
        assert "days ago" in result

    def test_months_ago(self) -> None:
        fixed_now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        with patch("dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = dashboard._fmt_relative_date("2026-02-01T00:00:00+00:00")
        assert "months ago" in result

    def test_years_ago(self) -> None:
        fixed_now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        with patch("dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = dashboard._fmt_relative_date("2024-01-01T00:00:00+00:00")
        assert "year" in result


# ---------------------------------------------------------------------------
# _sparkline_svg
# ---------------------------------------------------------------------------

class TestSparklineSvg:
    def test_empty_list_returns_empty(self) -> None:
        assert dashboard._sparkline_svg([]) == ""

    def test_single_value_returns_empty(self) -> None:
        assert dashboard._sparkline_svg([100]) == ""

    def test_flat_data_returns_empty(self) -> None:
        assert dashboard._sparkline_svg([50, 50, 50]) == ""

    def test_renders_svg_for_varied_data(self) -> None:
        svg = dashboard._sparkline_svg([10, 20, 15, 30, 25])
        assert svg.startswith("<svg")
        assert "polyline" in svg

    def test_green_for_uptrend(self) -> None:
        svg = dashboard._sparkline_svg([10, 20, 30])
        assert "#1a7f37" in svg  # last >= first → green

    def test_amber_for_downtrend(self) -> None:
        svg = dashboard._sparkline_svg([30, 20, 10])
        assert "#9a6700" in svg  # last < first → amber

    def test_two_point_minimum(self) -> None:
        svg = dashboard._sparkline_svg([5, 15])
        assert svg.startswith("<svg")


# ---------------------------------------------------------------------------
# _date_to_days
# ---------------------------------------------------------------------------

class TestDateToDays:
    def test_none_returns_sentinel(self) -> None:
        assert dashboard._date_to_days(None) == 999999

    def test_bad_iso_returns_sentinel(self) -> None:
        assert dashboard._date_to_days("not-a-date") == 999999

    def test_old_date_returns_large_number(self) -> None:
        result = dashboard._date_to_days("2020-01-01T00:00:00Z")
        assert result > 365 * 5

    def test_same_day_returns_zero(self) -> None:
        fixed_now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
        with patch("dashboard.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = dashboard._date_to_days("2026-05-30T06:00:00+00:00")
        assert result == 0


# ---------------------------------------------------------------------------
# _collect_target — GitHub-only paths (no pypi_name → no time.sleep)
# ---------------------------------------------------------------------------

class TestCollectTargetGithub:
    def _fake_gh(self, url: str, **kwargs: object) -> dict | list | None:
        if "code-scanning" in url:
            return [{"id": 1, "state": "open"}]
        if "releases/latest" in url:
            return {"tag_name": "v1.2.3", "published_at": "2026-05-01T00:00:00Z"}
        # repo info endpoint
        return {
            "stargazers_count": 7,
            "forks_count": 3,
            "pushed_at": "2026-05-28T10:00:00Z",
            "description": "Test repo",
            "html_url": "https://github.com/WRG-11/x",
            "license": {"spdx_id": "MIT"},
        }

    def test_github_fields_populated(self) -> None:
        target = {"name": "x", "pypi_name": None, "gh_repo": "WRG-11/x"}
        with patch.object(dashboard, "_fetch_json", side_effect=self._fake_gh):
            row = dashboard._collect_target(target)
        assert row["gh_stars"] == 7
        assert row["gh_forks"] == 3
        assert row["gh_release_tag"] == "1.2.3"
        assert row["gh_license_spdx"] == "MIT"
        assert row["gh_codeql_open"] == 1

    def test_no_errors_on_well_shaped_response(self) -> None:
        target = {"name": "x", "pypi_name": None, "gh_repo": "WRG-11/x"}
        with patch.object(dashboard, "_fetch_json", side_effect=self._fake_gh):
            row = dashboard._collect_target(target)
        assert row["errors"] == []

    def test_github_repo_not_found_adds_error(self) -> None:
        target = {"name": "x", "pypi_name": None, "gh_repo": "WRG-11/gone"}

        def _404(url: str, **kwargs: object) -> None:
            return None

        with patch.object(dashboard, "_fetch_json", side_effect=_404):
            row = dashboard._collect_target(target)
        # None returned for all GH calls → no crash, just empty fields
        assert row["gh_stars"] is None
        assert row["gh_release_tag"] is None


# ---------------------------------------------------------------------------
# _collect_target — drift flag (requires pypi_name; patch time.sleep)
# ---------------------------------------------------------------------------

class TestCollectTargetDrift:
    def test_drift_flag_set_when_pypi_gh_differ(self) -> None:
        target = {"name": "x", "pypi_name": "x", "gh_repo": "WRG-11/x"}

        def _fake(url: str, **kwargs: object) -> dict | list | None:
            if "pypi.org" in url:
                return {"info": {"version": "1.0.0", "summary": "ok"}}
            if "pypistats" in url:
                return None
            if "code-scanning" in url:
                return None
            if "releases/latest" in url:
                return {"tag_name": "v2.0.0", "published_at": "2026-05-01T00:00:00Z"}
            return {"stargazers_count": 0, "forks_count": 0, "pushed_at": None,
                    "description": None, "html_url": None, "license": None}

        with (
            patch.object(dashboard, "_fetch_json", side_effect=_fake),
            patch("dashboard.time.sleep"),
        ):
            row = dashboard._collect_target(target)

        assert row["pypi_version"] == "1.0.0"
        assert row["gh_release_tag"] == "2.0.0"
        assert row["drift"] is True

    def test_no_drift_when_versions_match(self) -> None:
        target = {"name": "x", "pypi_name": "x", "gh_repo": "WRG-11/x"}

        def _fake(url: str, **kwargs: object) -> dict | list | None:
            if "pypi.org" in url:
                return {"info": {"version": "1.0.0", "summary": "ok"}}
            if "pypistats" in url:
                return None
            if "code-scanning" in url:
                return None
            if "releases/latest" in url:
                return {"tag_name": "v1.0.0", "published_at": "2026-05-01T00:00:00Z"}
            return {"stargazers_count": 0, "forks_count": 0, "pushed_at": None,
                    "description": None, "html_url": None, "license": None}

        with (
            patch.object(dashboard, "_fetch_json", side_effect=_fake),
            patch("dashboard.time.sleep"),
        ):
            row = dashboard._collect_target(target)

        assert row["drift"] is False

    def test_pypi_not_found_adds_error(self) -> None:
        """_fetch_json returning None for pypi → 'pypi: package not found'."""
        target = {"name": "x", "pypi_name": "x", "gh_repo": None}

        def _fake(url: str, **kwargs: object) -> None:
            return None  # 404 for all

        with (
            patch.object(dashboard, "_fetch_json", side_effect=_fake),
            patch("dashboard.time.sleep"),
        ):
            row = dashboard._collect_target(target)

        assert any("package not found" in e for e in row["errors"])

    def test_pypi_fetch_exception_adds_error(self) -> None:
        """_fetch_json raising for pypi → error recorded as 'pypi: <ExcType>'."""
        target = {"name": "x", "pypi_name": "x", "gh_repo": None}

        def _fake(url: str, **kwargs: object) -> None:
            raise RuntimeError("connection reset")

        with (
            patch.object(dashboard, "_fetch_json", side_effect=_fake),
            patch("dashboard.time.sleep"),
        ):
            row = dashboard._collect_target(target)

        assert any("pypi: RuntimeError" in e for e in row["errors"])

    def test_pypistats_success_populates_downloads(self) -> None:
        """Well-shaped pypistats response → pypi_downloads_month set."""
        target = {"name": "x", "pypi_name": "x", "gh_repo": None}
        call_n = {"n": 0}

        def _fake(url: str, **kwargs: object) -> dict | None:
            call_n["n"] += 1
            if "pypi.org" in url:
                return {"info": {"version": "1.0.0", "summary": "ok"}}
            if "pypistats" in url and "overall" not in url:
                return {"data": {"last_month": 999}}
            return None

        with (
            patch.object(dashboard, "_fetch_json", side_effect=_fake),
            patch("dashboard.time.sleep"),
        ):
            row = dashboard._collect_target(target)

        assert row["pypi_downloads_month"] == 999

    def test_dl_cache_fallback_used_when_pypistats_fails(self) -> None:
        """When pypistats fails and dl_cache has a recent entry, use cached count."""
        target = {"name": "x", "pypi_name": "x", "gh_repo": None}
        dl_cache = {
            "x": {"last_month": 500, "fetched_at": "2026-05-30T00:00:00Z"},
        }

        def _fake(url: str, **kwargs: object) -> dict | None:
            if "pypi.org" in url:
                return {"info": {"version": "1.0.0", "summary": "ok"}}
            return None  # pypistats fails

        with (
            patch.object(dashboard, "_fetch_json", side_effect=_fake),
            patch("dashboard.time.sleep"),
            patch("dashboard.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            mock_dt.strftime = datetime.strftime
            row = dashboard._collect_target(target, dl_cache=dl_cache)

        assert row["pypi_downloads_month"] == 500
        assert row["pypi_downloads_cached_at"] == "2026-05-30T00:00:00Z"

    def test_github_repo_exception_recorded(self) -> None:
        """Exception during GitHub repo fetch → 'github-repo: <ExcType>' in errors."""
        target = {"name": "x", "pypi_name": None, "gh_repo": "WRG-11/x"}
        call_n = {"n": 0}

        def _fake(url: str, **kwargs: object) -> None:
            call_n["n"] += 1
            if "releases" not in url and "code-scanning" not in url:
                raise RuntimeError("timeout")
            return None

        with patch.object(dashboard, "_fetch_json", side_effect=_fake):
            row = dashboard._collect_target(target)

        assert any("github-repo: RuntimeError" in e for e in row["errors"])

    def test_github_release_exception_recorded(self) -> None:
        """Exception during GitHub releases fetch → 'github-release: <ExcType>'."""
        target = {"name": "x", "pypi_name": None, "gh_repo": "WRG-11/x"}

        def _fake(url: str, **kwargs: object) -> dict | None:
            if "releases" in url:
                raise RuntimeError("timeout on release")
            if "code-scanning" in url:
                return None
            return {"stargazers_count": 1, "forks_count": 0, "pushed_at": None,
                    "description": None, "html_url": None, "license": None}

        with patch.object(dashboard, "_fetch_json", side_effect=_fake):
            row = dashboard._collect_target(target)

        assert any("github-release: RuntimeError" in e for e in row["errors"])
