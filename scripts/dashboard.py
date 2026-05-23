"""WRG-11 portfolio dashboard -- single-page HTML, zero-dep stdlib.

For each target in config/sentry-targets.json (re-used so the dashboard
and the sentry stay in lock-step on what is "in the portfolio"), the
generator fetches:

  - PyPI  : .info.version + .info.summary from pypi.org/pypi/<name>/json
  - PyPI  : last_month downloads from pypistats.org/api/packages/<name>/recent
  - GitHub: .stargazers_count + .forks_count + .pushed_at + .description
            + .html_url from api.github.com/repos/<owner>/<repo>
  - GitHub: latest release .tag_name + .published_at from /releases/latest

And renders one HTML file (docs/index.html) suitable for GitHub Pages
serving from the main branch /docs folder. No JavaScript, no external
CSS, no fonts -- the page is fully self-contained and works offline.

Failure mode: per-target query errors are folded into the row as a
muted "?" cell rather than crashing the whole render. The page always
generates, even if half the upstream APIs are down. The footer notes
how many targets failed.

Zero-dep stdlib only: urllib.request + urllib.error + json + html +
argparse + pathlib + datetime + sys. Runs on any Python 3.10+ with
no `pip install` required.

Usage:

    python scripts/dashboard.py \\
        --config config/sentry-targets.json \\
        --out docs/index.html

Exit code 0 always (a partial render is still a useful render). Use
the sentry workflow for green/red gating.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "wrg-portfolio-dashboard/1.0 (+https://github.com/WRG-11/wrg-portfolio)"
TIMEOUT_SECONDS = 15


def _fetch_json(url: str, *, accept_404: bool = False) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if accept_404 and exc.code == 404:
            return None
        raise


def _normalize_version(raw: str) -> str:
    text = (raw or "").strip()
    if text.lower().startswith("v"):
        text = text[1:]
    return text


def _fmt_int(n: int | None) -> str:
    if n is None:
        return "?"
    if n >= 1000:
        return f"{n:,}".replace(",", ",")
    return str(n)


def _fmt_relative_date(iso: str | None) -> str:
    """Render '2026-05-23T14:00:00Z' as 'today' / 'yesterday' / 'N days ago'."""
    if not iso:
        return "?"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    days = (datetime.now(timezone.utc) - dt).days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    if days < 365:
        return f"{days // 30} months ago"
    years = days // 365
    return f"{years} year{'s' if years > 1 else ''} ago"


def _collect_target(target: dict[str, Any]) -> dict[str, Any]:
    """Best-effort multi-source query. Records errors per source but never raises."""
    row: dict[str, Any] = {
        "name": target.get("name", "?"),
        "pypi_name": target.get("pypi_name"),
        "gh_repo": target.get("gh_repo"),
        "pypi_version": None,
        "pypi_summary": None,
        "pypi_downloads_month": None,
        "gh_release_tag": None,
        "gh_release_date": None,
        "gh_stars": None,
        "gh_forks": None,
        "gh_pushed_at": None,
        "gh_description": None,
        "gh_html_url": None,
        "drift": False,
        "errors": [],
    }

    if row["pypi_name"]:
        try:
            payload = _fetch_json(f"https://pypi.org/pypi/{row['pypi_name']}/json", accept_404=True)
            if payload:
                row["pypi_version"] = _normalize_version(payload["info"]["version"])
                row["pypi_summary"] = payload["info"].get("summary") or ""
            else:
                row["errors"].append("pypi: package not found")
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"pypi: {exc.__class__.__name__}")

        try:
            stats = _fetch_json(f"https://pypistats.org/api/packages/{row['pypi_name']}/recent", accept_404=True)
            if stats and "data" in stats:
                row["pypi_downloads_month"] = stats["data"].get("last_month")
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"pypistats: {exc.__class__.__name__}")

    if row["gh_repo"]:
        try:
            repo_info = _fetch_json(f"https://api.github.com/repos/{row['gh_repo']}", accept_404=True)
            if repo_info:
                row["gh_stars"] = repo_info.get("stargazers_count")
                row["gh_forks"] = repo_info.get("forks_count")
                row["gh_pushed_at"] = repo_info.get("pushed_at")
                row["gh_description"] = repo_info.get("description")
                row["gh_html_url"] = repo_info.get("html_url")
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"github-repo: {exc.__class__.__name__}")

        try:
            release = _fetch_json(f"https://api.github.com/repos/{row['gh_repo']}/releases/latest", accept_404=True)
            if release:
                row["gh_release_tag"] = _normalize_version(release.get("tag_name", ""))
                row["gh_release_date"] = release.get("published_at")
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"github-release: {exc.__class__.__name__}")

    if row["pypi_version"] and row["gh_release_tag"]:
        row["drift"] = (row["pypi_version"] != row["gh_release_tag"])

    return row


# --- Rendering ------------------------------------------------------------


_CSS = """
* { box-sizing: border-box }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  max-width: 1100px;
  margin: 2em auto;
  padding: 0 1em;
  color: #24292f;
  line-height: 1.5;
}
h1 { margin-bottom: 0.2em; }
.lede { color: #57606a; margin-top: 0; }
table { border-collapse: collapse; width: 100%; margin-top: 1em; }
th, td { padding: 0.6em 0.8em; border-bottom: 1px solid #eaeef2; text-align: left; vertical-align: top; font-size: 0.95em; }
th { background: #f6f8fa; font-weight: 600; }
tr:hover td { background: #fafbfc; }
.pkg-name { font-weight: 600; }
.pkg-name a { color: #0969da; text-decoration: none; }
.pkg-name a:hover { text-decoration: underline; }
.pkg-desc { color: #57606a; font-size: 0.85em; margin-top: 0.2em; }
.ver { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.9em; }
.ok { color: #1a7f37; font-weight: 600; }
.drift { color: #cf222e; font-weight: 600; }
.muted { color: #8c959f; }
.footer { color: #6e7781; font-size: 0.85em; margin-top: 3em; border-top: 1px solid #eaeef2; padding-top: 1em; }
.footer a { color: #0969da; }
.metric { font-variant-numeric: tabular-nums; }
"""


def _render_row(row: dict[str, Any]) -> str:
    pypi = row["pypi_version"]
    gh = row["gh_release_tag"]
    if pypi and gh and pypi == gh:
        status_html = '<span class="ok">OK</span>'
    elif row["drift"]:
        status_html = '<span class="drift">DRIFT</span>'
    elif row["errors"]:
        status_html = '<span class="muted">?</span>'
    else:
        status_html = '<span class="muted">-</span>'

    name = html.escape(row["name"])
    repo = html.escape(row["gh_repo"] or "")
    url = row["gh_html_url"] or (f"https://github.com/{row['gh_repo']}" if row["gh_repo"] else "#")
    desc = html.escape(row["gh_description"] or row["pypi_summary"] or "")

    name_cell = f'<span class="pkg-name"><a href="{html.escape(url)}">{name}</a></span>'
    if desc:
        name_cell += f'<div class="pkg-desc">{desc}</div>'

    return (
        "<tr>"
        f"<td>{name_cell}</td>"
        f'<td class="ver">{html.escape(pypi) if pypi else "<span class=\"muted\">-</span>"}</td>'
        f'<td class="ver">{html.escape(gh) if gh else "<span class=\"muted\">-</span>"}</td>'
        f"<td>{status_html}</td>"
        f'<td class="metric">{_fmt_int(row["pypi_downloads_month"])}</td>'
        f'<td class="metric">{_fmt_int(row["gh_stars"])}</td>'
        f'<td class="metric">{_fmt_int(row["gh_forks"])}</td>'
        f'<td>{html.escape(_fmt_relative_date(row["gh_pushed_at"]))}</td>'
        "</tr>"
    )


def _render_html(rows: list[dict[str, Any]], generated_at: datetime) -> str:
    table_rows = "\n      ".join(_render_row(r) for r in rows)
    failed = sum(1 for r in rows if r["errors"])
    drift = sum(1 for r in rows if r["drift"])
    ok = sum(1 for r in rows if r["pypi_version"] and r["gh_release_tag"] and not r["drift"])

    summary_parts = [f"{ok} OK", f"{drift} DRIFT"]
    if failed:
        summary_parts.append(f"{failed} with query errors")
    summary = " | ".join(summary_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>WRG-11 Portfolio</title>
<style>{_CSS}</style>
</head>
<body>
  <h1>WRG-11 Portfolio</h1>
  <p class="lede">Open-source security tooling for AI/LLM defense, detection
  engineering, threat intelligence, and OSINT. Zero-dependency Python where
  it makes sense; MIT licensed across the ecosystem.</p>

  <p><strong>Snapshot:</strong> {summary}</p>

  <table>
    <thead>
      <tr>
        <th>Package</th>
        <th>PyPI</th>
        <th>GH Release</th>
        <th>Status</th>
        <th>Downloads (30d)</th>
        <th>Stars</th>
        <th>Forks</th>
        <th>Last commit</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>

  <p class="footer">
    Generated {generated_at.strftime("%Y-%m-%d %H:%M UTC")} by
    <a href="https://github.com/WRG-11/wrg-portfolio">wrg-portfolio</a>
    (version-sentry sister). Daily auto-refresh via GitHub Actions cron.
    Data sources: pypi.org, pypistats.org, api.github.com. No tracking,
    no JavaScript, no external assets.
  </p>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="WRG-11 portfolio dashboard generator")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="path to write HTML")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"[dashboard] config not found: {args.config}", file=sys.stderr)
        return 2
    config = json.loads(args.config.read_text(encoding="utf-8"))
    targets = config.get("targets") or []
    if not targets:
        print("[dashboard] no targets in config", file=sys.stderr)
        return 2

    rows = [_collect_target(t) for t in targets]
    generated_at = datetime.now(timezone.utc)
    html_doc = _render_html(rows, generated_at)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_doc, encoding="utf-8")

    failed = sum(1 for r in rows if r["errors"])
    print(f"[dashboard] wrote {args.out} ({len(rows)} rows, {failed} with query errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
