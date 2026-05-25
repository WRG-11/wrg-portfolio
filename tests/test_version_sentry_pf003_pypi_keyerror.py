"""R89-14b H Wave 6 PF-003 regression: PyPI / GH degraded-shape handling.

Before PF-003 the code did ``payload["info"]["version"]`` and
``payload["tag_name"]`` — raw indexed access. When PyPI returned a
degraded shape (no ``info`` key during partial outage) the KeyError
bubbled through ``_check_target`` and became the misleading "pypi
query failed: KeyError: 'info'" — looked like a network error but
was really a schema-shape error.

After PF-003 the helpers use ``.get`` walks + explicit
``ValueError("... degraded API response shape ...")`` so the operator
sees a specific diagnostic.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import version_sentry  # noqa: E402  -- via tests/conftest.py sys.path


def test_query_pypi_version_missing_info_pf003() -> None:
    """PyPI returned no ``info`` key → ValueError with shape clue."""
    with patch.object(version_sentry, "_fetch_json", return_value={}):
        with pytest.raises(ValueError, match="missing info.version"):
            version_sentry._query_pypi_version("missing-info")


def test_query_pypi_version_missing_version_subkey_pf003() -> None:
    """PyPI returned ``info`` but no ``version`` → ValueError."""
    with patch.object(
        version_sentry, "_fetch_json",
        return_value={"info": {"summary": "without version"}},
    ):
        with pytest.raises(ValueError, match="missing info.version"):
            version_sentry._query_pypi_version("missing-version")


def test_query_pypi_version_happy_path_pf003() -> None:
    """Sanity: well-shaped response still returns version."""
    with patch.object(
        version_sentry, "_fetch_json",
        return_value={"info": {"version": "v1.2.3"}},
    ):
        assert version_sentry._query_pypi_version("ok") == "1.2.3"


def test_query_github_release_missing_tag_name_pf003() -> None:
    """GH Releases returned no ``tag_name`` → ValueError with shape clue."""
    with patch.object(
        version_sentry, "_fetch_json",
        return_value={"name": "Release 1.0"},  # no tag_name
    ):
        with pytest.raises(ValueError, match="missing tag_name"):
            version_sentry._query_github_release("WRG-11/x")


def test_query_github_release_happy_path_pf003() -> None:
    """Sanity: well-shaped GH response still returns normalised tag."""
    with patch.object(
        version_sentry, "_fetch_json",
        return_value={"tag_name": "v9.9.9"},
    ):
        assert version_sentry._query_github_release("WRG-11/x") == "9.9.9"
