"""R89-14b H Wave 6 PF-004 regression: dashboard.py PyPI degraded shape.

Sister of version_sentry PF-003. Before PF-004 the inline
``payload["info"]["version"]`` raised KeyError on a PyPI response
missing the ``info`` key, and the caller logged it as the generic
``"pypi: KeyError"``. After PF-004 the same code path detects the
degraded shape and logs ``"pypi: degraded shape (no info.version)"``
or ``"pypi: degraded shape (no info object)"``.
"""
from __future__ import annotations

from unittest.mock import patch

import dashboard  # noqa: E402  -- via tests/conftest.py sys.path


def test_collect_target_pypi_no_info_pf004() -> None:
    """PyPI response with non-dict ``info`` → recorded as degraded shape.

    Note: an empty ``{}`` payload is treated as "package not found"
    by the existing ``if payload:`` check (truthy guard). The
    degraded-shape branch fires when the payload is non-empty but
    ``info`` is missing or non-dict (e.g. PyPI returns
    ``{"info": null, "urls": []}`` during a partial outage).
    """
    target = {"name": "x", "pypi_name": "x", "gh_repo": None}
    with patch.object(
        dashboard, "_fetch_json",
        return_value={"info": None, "urls": []},
    ):
        row = dashboard._collect_target(target)
    assert any(
        "degraded shape (no info object)" in e for e in row["errors"]
    ), f"PF-004: expected degraded-shape error, got {row['errors']!r}"
    assert row["pypi_version"] is None


def test_collect_target_pypi_no_version_subkey_pf004() -> None:
    """PyPI returned ``info`` but no ``version`` → degraded shape."""
    target = {"name": "x", "pypi_name": "x", "gh_repo": None}
    with patch.object(
        dashboard, "_fetch_json",
        return_value={"info": {"summary": "no version field"}},
    ):
        row = dashboard._collect_target(target)
    assert any(
        "degraded shape (no info.version)" in e for e in row["errors"]
    )
    assert row["pypi_version"] is None
    # Summary should still come through even when version is missing.
    assert row["pypi_summary"] == "no version field"


def test_collect_target_pypi_happy_path_pf004() -> None:
    """Sanity: well-shaped response still populates version + summary."""
    target = {"name": "x", "pypi_name": "x", "gh_repo": None}
    with patch.object(
        dashboard, "_fetch_json",
        return_value={"info": {"version": "v1.0.0", "summary": "ok"}},
    ):
        row = dashboard._collect_target(target)
    assert row["pypi_version"] == "1.0.0"
    assert row["pypi_summary"] == "ok"
    # No pypi-shape error in errors (other entries may exist from
    # pypistats / GH calls — only assert no pypi-shape complaint).
    assert not any("degraded shape" in e for e in row["errors"])
