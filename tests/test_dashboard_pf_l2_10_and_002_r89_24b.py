"""R89-24b PF-L2-10-001 + PF-L2-002 regression — dashboard config guards.

Pre-fix issues:
  - PF-L2-10-001: ``main()`` called ``json.loads(args.config.read_text(...))``
    unguarded. Malformed config (typo, manual edit, truncated write) raised
    a raw ``json.JSONDecodeError`` traceback with no indication that the
    config was the problem.
  - PF-L2-002: ``targets`` list was iterated via ``_collect_target(t, ...)``
    which called ``t.get(...)`` immediately. A non-dict entry (bare string
    'foo' or number 42 in the JSON array) raised ``AttributeError`` deep
    inside the per-target loop with no actionable diagnostic.

Post-fix: explicit try/except + isinstance filter at the entry point.
Operator gets a clean single-line diagnostic and a documented exit code
(2) instead of a Python traceback.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1] / "scripts" / "dashboard.py"


def _run(config_path: Path, tmp_out: Path):
    return subprocess.run(
        [sys.executable, str(DASHBOARD),
         "--config", str(config_path),
         "--out", str(tmp_out)],
        capture_output=True, text=True, timeout=30,
    )


def test_pf_l2_10_001_malformed_json_config_exits_2_with_clean_diagnostic(
    tmp_path: Path,
) -> None:
    """A typo'd config must exit 2 with a JSON-decode diagnostic."""
    config = tmp_path / "broken.json"
    config.write_text("{ this is not JSON, comma is missing\n}", encoding="utf-8")
    result = _run(config, tmp_path / "out.html")
    assert result.returncode == 2, (
        f"PF-L2-10-001: expected exit 2, got {result.returncode}.\n"
        f"stderr={result.stderr!r}"
    )
    assert "config JSON invalid" in result.stderr, (
        f"PF-L2-10-001: clean diagnostic missing. stderr={result.stderr!r}"
    )
    # No Python traceback should leak
    assert "Traceback" not in result.stderr


def test_pf_l2_10_001_non_object_root_rejected(tmp_path: Path) -> None:
    """Config root must be a JSON object, not a list/string/number."""
    config = tmp_path / "bad_root.json"
    config.write_text('["targets", "as", "a", "list"]', encoding="utf-8")
    result = _run(config, tmp_path / "out.html")
    assert result.returncode == 2
    assert "config root must be a JSON object" in result.stderr


def test_pf_l2_002_non_dict_targets_filtered_with_warning(tmp_path: Path) -> None:
    """Bare strings/numbers in targets array must be skipped with a warning."""
    config = tmp_path / "mixed.json"
    config.write_text(
        json.dumps({
            "targets": [
                "stringy-entry",       # invalid -- should be skipped
                42,                    # invalid -- should be skipped
                {"name": "valid-but-incomplete"},  # dict; will fail downstream but that's a different code path
            ]
        }),
        encoding="utf-8",
    )
    result = _run(config, tmp_path / "out.html")
    # Skip warning must appear; we don't assert success because the
    # remaining valid dict still needs PyPI/GH calls that may 404.
    assert "skipping" in result.stderr and "non-dict entries" in result.stderr, (
        f"PF-L2-002: skip warning missing. stderr={result.stderr!r}"
    )


def test_pf_l2_002_all_non_dict_targets_returns_2(tmp_path: Path) -> None:
    """If every target is non-dict, exit 2 with the right diagnostic."""
    config = tmp_path / "all_invalid.json"
    config.write_text(
        json.dumps({"targets": ["foo", 1, True]}),
        encoding="utf-8",
    )
    result = _run(config, tmp_path / "out.html")
    assert result.returncode == 2
    assert "no valid target entries" in result.stderr
