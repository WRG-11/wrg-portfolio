"""WRG-11 version sentry -- PyPI vs GitHub Releases drift detector.

For each target in the config file:
  1. Fetch the latest PyPI version from https://pypi.org/pypi/<name>/json
     (the JSON API returns .info.version for the current release)
  2. Fetch the latest GitHub Release tag from
     https://api.github.com/repos/<owner>/<repo>/releases/latest
  3. Normalize each version (strip optional leading 'v', trim whitespace)
  4. Compare. If they differ, record a DRIFT finding.

Output: JSON summary to stdout (and optionally to --json-out path).
Exit code 0 if no drift. Exit code 1 if any target drifted or failed
to query. Optional --create-issue opens a GitHub Issue on the host
repo (gh CLI; relies on GH_TOKEN env or local gh auth) summarising
the drift.

Zero-dep stdlib only: urllib.request + urllib.error + json + os +
subprocess + argparse + pathlib + datetime + sys. Runs on any Python
3.10+ with no `pip install` required -- which matters because this
sentry must work even when the WRG-11 packages it watches break.

Usage:

    python scripts/version_sentry.py \\
        --config config/sentry-targets.json \\
        --json-out sentry-report.json \\
        [--create-issue]

Exit codes:
    0   all targets in sync
    1   one or more targets drifted or failed to query
    2   config file missing or malformed
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "wrg-portfolio-version-sentry/1.0 (+https://github.com/WRG-11/wrg-portfolio)"
TIMEOUT_SECONDS = 15


def _normalize_version(raw: str) -> str:
    """Strip whitespace + an optional leading 'v' (common tag style)."""
    text = (raw or "").strip()
    if text.lower().startswith("v"):
        text = text[1:]
    return text


def _fetch_json(url: str, *, accept_404: bool = False) -> dict[str, Any] | None:
    """GET URL and return parsed JSON. None on 404 when accept_404 is True.

    R89-14b H Wave-6 PF-002 (sister to dashboard.py PF-001): previously
    only ``HTTPError`` was caught. ``URLError`` (DNS, conn-refused, TLS)
    raised through to ``_check_target``'s ``except Exception`` where it
    was indistinguishable from any other programming bug in the same
    try block. Specific-exception locality: raise ``ValueError`` with a
    clear "network unavailable" message so the cause is named.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if accept_404 and exc.code == 404:
            return None
        raise
    except urllib.error.URLError as exc:
        # R89-14b H PF-002: name the exception specifically so it is
        # not lumped into the catch-all caller branch.
        raise ValueError(f"network unavailable fetching {url}: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # R89-14b H PF-005 sister: HTML / non-JSON response body
        # (captive portal, proxy interstitial, edge 502-as-200).
        # Surface as a named ValueError so the operator sees the cause.
        raise ValueError(
            f"non-JSON response from {url}: {exc.__class__.__name__}"
        ) from exc


def _query_pypi_version(name: str) -> str:
    """Fetch latest published version from pypi.org JSON API.

    R89-14b H Wave-6 PF-003: previously ``payload["info"]["version"]``
    raised KeyError on a degraded PyPI response (missing ``info`` key,
    or missing ``version`` within). KeyError bubbled to caller's
    ``except Exception`` where it became ``"pypi query failed:
    KeyError: 'info'"`` — looks like a network error but is actually a
    schema-shape error. ``.get`` walk + explicit ValueError clarifies.
    """
    payload = _fetch_json(f"https://pypi.org/pypi/{name}/json", accept_404=True)
    if payload is None:
        raise ValueError(f"PyPI package not found: {name}")
    info = payload.get("info") if isinstance(payload, dict) else None
    version = (info or {}).get("version") if isinstance(info, dict) else None
    if not version:
        raise ValueError(
            f"PyPI response for {name} is missing info.version "
            f"(degraded API response shape)"
        )
    return _normalize_version(version)


def _query_github_release(repo: str) -> str:
    """Fetch latest GitHub Release tag (NOT just latest tag) for owner/repo.

    R89-14b H PF-003 sister: same defensive .get walk applied to the
    GitHub Releases payload (``tag_name`` missing on partial responses).
    """
    payload = _fetch_json(f"https://api.github.com/repos/{repo}/releases/latest", accept_404=True)
    if payload is None:
        raise ValueError(f"No GitHub Releases for: {repo}")
    tag_name = payload.get("tag_name") if isinstance(payload, dict) else None
    if not tag_name:
        raise ValueError(
            f"GitHub Releases response for {repo} is missing tag_name "
            f"(degraded API response shape)"
        )
    return _normalize_version(tag_name)


def _check_target(target: dict[str, Any]) -> dict[str, Any]:
    """Query one target. Always returns a finding dict (never raises)."""
    name = target.get("name", "?")
    pypi_name = target.get("pypi_name")
    gh_repo = target.get("gh_repo")
    finding: dict[str, Any] = {
        "name": name,
        "pypi_name": pypi_name,
        "gh_repo": gh_repo,
        "pypi_version": None,
        "gh_release": None,
        "status": "OK",
        "error": None,
    }

    try:
        if pypi_name:
            finding["pypi_version"] = _query_pypi_version(pypi_name)
    except Exception as exc:  # noqa: BLE001 -- any failure is a finding
        finding["status"] = "ERROR"
        finding["error"] = f"pypi query failed: {exc.__class__.__name__}: {exc}"
        return finding

    try:
        if gh_repo:
            finding["gh_release"] = _query_github_release(gh_repo)
    except Exception as exc:  # noqa: BLE001
        finding["status"] = "ERROR"
        finding["error"] = f"github query failed: {exc.__class__.__name__}: {exc}"
        return finding

    pypi = finding["pypi_version"]
    gh = finding["gh_release"]
    if pypi and gh and pypi != gh:
        finding["status"] = "DRIFT"
        finding["error"] = (
            f"PyPI version ({pypi}) does not match latest GitHub Release ({gh})"
        )
    elif not (pypi and gh):
        finding["status"] = "INCOMPLETE"
        finding["error"] = "missing pypi_name or gh_repo (or no releases yet)"

    return finding


def _build_report(findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for f in findings:
        by_status[f["status"]] = by_status.get(f["status"], 0) + 1
    return {
        "schema_version": "wrg_portfolio.version_sentry.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "targets_checked": len(findings),
        "by_status": by_status,
        "findings": findings,
    }


def _maybe_create_issue(report: dict[str, Any], repo: str) -> None:
    """Open one GitHub Issue summarising drift (only if drift was found)."""
    bad = [f for f in report["findings"] if f["status"] in {"DRIFT", "ERROR"}]
    if not bad:
        return

    today = report["created_at"][:10]
    title = f"[sentry] version drift detected on {today} -- {len(bad)} target(s)"
    body_lines = [
        "Automated version sentry caught a drift between PyPI and GitHub",
        "Releases for one or more WRG-11 packages. Details below; the",
        "full JSON report is attached to the workflow run as an artifact.",
        "",
        "| Target | PyPI | GH Release | Status | Detail |",
        "|---|---|---|---|---|",
    ]
    for f in bad:
        body_lines.append(
            "| {name} | {pypi} | {gh} | {status} | {err} |".format(
                name=f["name"],
                pypi=f["pypi_version"] or "n/a",
                gh=f["gh_release"] or "n/a",
                status=f["status"],
                err=(f["error"] or "").replace("|", "\\|"),
            )
        )
    body_lines.extend([
        "",
        "Likely causes:",
        "- PyPI release succeeded but the matching git tag was not pushed.",
        "- Git tag pushed but the PyPI publish workflow failed.",
        "- A repo was renamed or moved (PyPI name now stale).",
        "- The GitHub Release was deleted or de-published.",
        "",
        f"Sentry config: `config/sentry-targets.json` on {repo}.",
        f"Run UTC: {report['created_at']}",
    ])

    body = "\n".join(body_lines)
    cmd = [
        "gh", "issue", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
        "--label", "version-sentry",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # Don't fail the sentry just because issue creation failed.
        # Print to stderr so the GHA log shows it.
        print(f"[sentry] gh issue create failed (rc={proc.returncode}): {proc.stderr.strip()}", file=sys.stderr)
    else:
        print(f"[sentry] opened drift issue: {proc.stdout.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="WRG-11 version sentry")
    parser.add_argument(
        "--config", required=True, type=Path,
        help="JSON config (e.g. config/sentry-targets.json)",
    )
    parser.add_argument(
        "--json-out", type=Path, default=None,
        help="write full JSON report to this path",
    )
    parser.add_argument(
        "--create-issue", action="store_true",
        help="open a GitHub Issue when drift is detected (requires gh CLI + GH_TOKEN)",
    )
    parser.add_argument(
        "--issue-repo", default=os.environ.get("GITHUB_REPOSITORY", "WRG-11/wrg-portfolio"),
        help="repo to file drift issues against (default $GITHUB_REPOSITORY or WRG-11/wrg-portfolio)",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"[sentry] config not found: {args.config}", file=sys.stderr)
        return 2
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[sentry] config is not valid JSON: {exc}", file=sys.stderr)
        return 2

    targets = config.get("targets") or []
    if not targets:
        print("[sentry] no targets in config", file=sys.stderr)
        return 2

    findings = [_check_target(t) for t in targets]
    report = _build_report(findings)

    serialized = json.dumps(report, indent=2, sort_keys=True)
    print(serialized)
    if args.json_out:
        args.json_out.write_text(serialized + "\n", encoding="utf-8")

    drift_or_error = any(f["status"] in {"DRIFT", "ERROR"} for f in findings)
    if args.create_issue and drift_or_error:
        _maybe_create_issue(report, args.issue_repo)

    return 1 if drift_or_error else 0


if __name__ == "__main__":
    sys.exit(main())
