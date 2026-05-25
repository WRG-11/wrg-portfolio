"""Shared pytest fixtures for wrg-portfolio scripts/.

The dashboard + version_sentry modules live under ``scripts/`` rather
than a package directory (zero-dep stdlib design — they're meant to
be ``python scripts/<name>.py`` invocable). This conftest adds
``scripts/`` to ``sys.path`` so the test files can ``import
dashboard`` / ``import version_sentry`` directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
