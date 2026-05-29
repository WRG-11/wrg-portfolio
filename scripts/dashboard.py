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
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "wrg-portfolio-dashboard/1.0 (+https://github.com/WRG-11/wrg-portfolio)"
TIMEOUT_SECONDS = 15
RATE_LIMIT_BACKOFF_SECONDS = 7  # pypistats throttles ~10 req/min; one cool-down is enough
PYPISTATS_INTERCALL_DELAY = 3.0  # R89-18a fix #2: 3s spacing between pypistats calls.
                                 # Empirical: 2s sometimes insufficient (last call in a
                                 # 4-target run got throttled); 3s = 20 calls/min ceiling
                                 # with safety margin under the ~10 req/min API floor.
                                 # Cost: ~12s extra runtime per dashboard generation.

# R89-18a fix #1: read GitHub PAT from env once at module load.
# When set, threaded into code-scanning/alerts requests so that
# private alert visibility (default for new repos) returns real
# numbers instead of HTTP 401 → "?". Falls back to anonymous if
# unset, preserving the original public-only behaviour.
GH_AUTH_TOKEN = os.environ.get("GH_DASHBOARD_TOKEN") or os.environ.get("GITHUB_TOKEN")

# R89-18a enhancement C: pypistats download cache.
# Persisted last-known-good download counts so that when pypistats
# throttles a target on this run, the dashboard renders the cached
# value with a "stale (Nh)" indicator instead of "?". Eliminates the
# rotation pattern where 1-2 of 4 packages rendered "?" per run on
# the GHA shared runner IP. Cache lives in data/dl_cache.json and is
# committed alongside docs/index.html — small file (~5 entries × 3
# fields), no .gitignore needed.
DL_CACHE_PATH = Path("data/dl_cache.json")
DL_CACHE_STALE_HOURS = 168  # 7 days — beyond this, treat cache as too stale to display
# R89-60f Feature 3: sparkline 7-day cache TTL. Shorter than DL_CACHE_STALE_HOURS
# (168h) because sparkline shape matters more than the absolute number; 20h gives
# roughly daily refresh cadence without a separate API call on every dashboard run
# once the cache is warm.
SPARKLINE_CACHE_STALE_HOURS = 20


def _fetch_json(
    url: str,
    *,
    accept_404: bool = False,
    retry_429: bool = False,
    auth_token: str | None = None,
) -> dict[str, Any] | None:
    """GET URL and return parsed JSON. None on 404 when accept_404 is True.
    When retry_429 is True, one retry after a short cool-down is performed
    on HTTP 429 (rate limit). pypistats.org imposes ~10 req/min so the
    cool-down resolves transient throttling without inflating runtime.
    When auth_token is provided, sent as Bearer in the Authorization
    header — used for GitHub code-scanning/alerts endpoints that
    require auth even for own repos (R89-18a fix #1)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if accept_404 and exc.code == 404:
            return None
        if retry_429 and exc.code == 429:
            # R89-16b H PF-W7-01: honour the server-provided
            # Retry-After header (fixed-7s backoff was either too
            # short → re-trigger 429 → exhaust → None; or too long
            # → runtime inflation). Cap at 60s to prevent a hostile
            # / misconfigured server from stalling the dashboard.
            # Build a FRESH Request — defensive in case urllib mutates
            # internal state on first urlopen (Authorization-header
            # behaviour differs across CPython minor versions; cheap
            # belt-and-suspenders).
            retry_after_raw = exc.headers.get("Retry-After") if exc.headers else None
            try:
                retry_after = int(retry_after_raw) if retry_after_raw else RATE_LIMIT_BACKOFF_SECONDS
            except (TypeError, ValueError):
                retry_after = RATE_LIMIT_BACKOFF_SECONDS
            retry_after = max(1, min(retry_after, 60))
            time.sleep(retry_after)
            fresh_req = urllib.request.Request(url, headers=dict(headers))
            try:
                with urllib.request.urlopen(fresh_req, timeout=TIMEOUT_SECONDS) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.URLError:
                # R89-14b H PF-001 retry path: DNS / conn-refused on
                # the retry attempt degrades to None, same as primary.
                return None
        raise
    except urllib.error.URLError:
        # R89-14b H Wave-6 PF-001: previously only HTTPError was caught.
        # ``URLError`` (DNS failure, conn-refused, TLS handshake) bubbled
        # out and forced every caller to ``except Exception`` — too broad
        # (also swallows KeyError / TypeError programming bugs). Specific
        # locality: degrade to a "?" row instead.
        return None
    except (json.JSONDecodeError, UnicodeDecodeError):
        # R89-14b H Wave-6 PF-005: server returned non-JSON (HTML error
        # page, captive portal interstitial, proxy banner). Old code
        # bubbled JSONDecodeError into the caller's ``except Exception``;
        # specific-exception locality lets the dashboard treat this the
        # same as a 404 — "data unavailable" without an alarmist row
        # error.
        return None


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


def _load_dl_cache(path: Path) -> dict[str, dict[str, Any]]:
    """Load the persisted pypistats download cache. Returns empty dict if missing
    or malformed — never raises (cache is best-effort, never blocks the build)."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}


def _save_dl_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    """Persist the pypistats download cache. Silently no-ops on write failure
    so a read-only filesystem doesn't crash the dashboard."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # Non-critical write; dashboard renders from live data (safe on read-only FS)


def _cache_age_label(iso: str | None) -> str:
    """Render '2026-05-26T07:08:00Z' as 'cached 2h ago', 'cached 3d ago', etc.
    Returns '' on parse error so the cell still renders the number."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    delta = datetime.now(timezone.utc) - dt
    hours = int(delta.total_seconds() // 3600)
    if hours < 1:
        return "cached <1h ago"
    if hours < 24:
        return f"cached {hours}h ago"
    days = hours // 24
    return f"cached {days}d ago"


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


def _fetch_sparkline_data(
    pypi_name: str,
    dl_cache: dict[str, dict[str, Any]],
) -> list[int]:
    """Fetch 7-day daily download counts from pypistats overall endpoint.
    Returns list of up to 7 ints (oldest first) or [] on failure.
    Reads/writes sparkline_7d + sparkline_at in dl_cache for TTL-gated caching.

    Cache-warm (age <= SPARKLINE_CACHE_STALE_HOURS): instant return, no API call.
    Cache-cold: PYPISTATS_INTERCALL_DELAY sleep then live fetch. The delay keeps
    total pypistats rate under the ~10 req/min floor even on cache-cold first runs.
    """
    cached = dl_cache.get(pypi_name, {})
    if cached.get("sparkline_7d") and cached.get("sparkline_at"):
        try:
            dt = datetime.fromisoformat(cached["sparkline_at"].replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            if age_h <= SPARKLINE_CACHE_STALE_HOURS:
                return cached["sparkline_7d"]
        except (ValueError, TypeError):
            pass  # Malformed sparkline_at timestamp — treat as cache-cold, fall through to fetch

    # Cache cold or stale — delay then fetch.
    time.sleep(PYPISTATS_INTERCALL_DELAY)
    try:
        data = _fetch_json(
            f"https://pypistats.org/api/packages/{pypi_name}/overall",
            accept_404=True,
            retry_429=True,
        )
        if not data or "data" not in data:
            return cached.get("sparkline_7d") or []
        entries = [
            e for e in data["data"]
            if isinstance(e, dict) and e.get("category") == "without_mirrors"
        ]
        entries.sort(key=lambda e: e.get("date", ""))
        values = [
            int(e["downloads"])
            for e in entries[-7:]
            if e.get("downloads") is not None
        ]
        if values:
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            dl_cache.setdefault(pypi_name, {})
            dl_cache[pypi_name]["sparkline_7d"] = values
            dl_cache[pypi_name]["sparkline_at"] = now_iso
        return values
    except Exception:  # noqa: BLE001
        return cached.get("sparkline_7d") or []


def _sparkline_svg(values: list[int]) -> str:
    """Render a 48×16 inline SVG polyline sparkline from daily download counts.
    Green (#1a7f37) if last >= first (trend up/flat); amber (#9a6700) if down.
    Returns '' for < 2 values or flat data (min == max) — no useful visual.
    The SVG is embedded inline; no external asset, no JS required to display."""
    if not values or len(values) < 2:
        return ""
    mn = min(values)
    mx = max(values)
    if mx == mn:
        return ""  # flat line carries no trend information
    W, H = 48, 16
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = round(W * i / (n - 1), 1)
        y = round(H - H * (v - mn) / (mx - mn), 1)
        pts.append(f"{x},{y}")
    color = "#1a7f37" if values[-1] >= values[0] else "#9a6700"
    polyline = " ".join(pts)
    return (
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}"'
        f' style="vertical-align:middle;overflow:visible" aria-hidden="true">'
        f'<polyline points="{polyline}" fill="none" stroke="{color}"'
        f' stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )


def _date_to_days(iso: str | None) -> int:
    """Convert ISO timestamp to integer days-since-today (0=today, 999999=unknown).
    Used as numeric data-val for client-side sort on date columns (R89-60f F2).
    Ascending sort = most recent first (0 days, then 3 days, then 30 days…)."""
    if not iso:
        return 999999
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except ValueError:
        return 999999


def _collect_target(
    target: dict[str, Any],
    *,
    dl_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Best-effort multi-source query. Records errors per source but never raises.
    R89-18a enhancement C: when dl_cache is provided and pypistats fails for this
    target, fall back to the cached download count (with stale-age indicator)."""
    if dl_cache is None:
        dl_cache = {}
    row: dict[str, Any] = {
        "name": target.get("name", "?"),
        "pypi_name": target.get("pypi_name"),
        "gh_repo": target.get("gh_repo"),
        "channels": target.get("channels") or [],  # enhancement B
        # R89-60f: category tags for client-side filter (sentry-targets.json).
        "categories": target.get("categories") or [],
        # R89-58f: static fields from config (data-refresh wave; F R89-58f).
        # coverage_pct: test-coverage % from CI badge (F R89-48f badge wave).
        # glama_score: Glama License/Quality/Maintenance grade (e.g. "A/A/B").
        # description_override: dashboard description; takes precedence over
        #   gh_description fetched from GitHub API (for wrg-sigma-rules 61→67 fix).
        "coverage_pct": target.get("coverage_pct"),
        "glama_score": target.get("glama_score"),
        "description_override": target.get("description_override"),
        "pypi_version": None,
        "pypi_summary": None,
        "pypi_downloads_month": None,
        "pypi_downloads_cached_at": None,  # enhancement C: ISO timestamp if cached fallback
        "sparkline_svg": "",  # R89-60f F3: pre-generated 48×16 SVG string; empty if GH-only or flat
        "gh_release_tag": None,
        "gh_release_date": None,
        "gh_stars": None,
        "gh_forks": None,
        "gh_pushed_at": None,
        "gh_description": None,
        "gh_html_url": None,
        "gh_license_spdx": None,
        "gh_codeql_open": None,
        "drift": False,
        "errors": [],
    }

    if row["pypi_name"]:
        try:
            payload = _fetch_json(f"https://pypi.org/pypi/{row['pypi_name']}/json", accept_404=True)
            if payload:
                # R89-14b H Wave-6 PF-004 (sister of version_sentry PF-003):
                # PyPI degraded responses sometimes drop the ``info`` key
                # entirely. Old code did ``payload["info"]["version"]`` →
                # KeyError → caller logs generic "pypi: KeyError". Use a
                # defensive .get walk and record a specific "degraded
                # shape" error instead.
                info = payload.get("info") if isinstance(payload, dict) else None
                if isinstance(info, dict):
                    version = info.get("version")
                    if version:
                        row["pypi_version"] = _normalize_version(version)
                    else:
                        row["errors"].append("pypi: degraded shape (no info.version)")
                    row["pypi_summary"] = info.get("summary") or ""
                else:
                    row["errors"].append("pypi: degraded shape (no info object)")
            else:
                row["errors"].append("pypi: package not found")
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"pypi: {exc.__class__.__name__}")

        try:
            # R89-18a fix #2: inter-call delay before each pypistats hit.
            # pypistats has ~10 req/min floor; rapid-fire calls (no spacing
            # between 4-5 sequential targets) hit 429 even with retry_429
            # because the retry sleeps only on FAIL. Pre-emptive 2s spacing
            # keeps us comfortably under the floor.
            time.sleep(PYPISTATS_INTERCALL_DELAY)
            stats = _fetch_json(
                f"https://pypistats.org/api/packages/{row['pypi_name']}/recent",
                accept_404=True,
                retry_429=True,
            )
            if stats and "data" in stats and stats["data"].get("last_month") is not None:
                row["pypi_downloads_month"] = stats["data"]["last_month"]
                # R89-18a enhancement C: persist successful response for fallback.
                dl_cache[row["pypi_name"]] = {
                    "last_month": stats["data"]["last_month"],
                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"pypistats: {exc.__class__.__name__}")

        # R89-18a enhancement C: cache fallback. If pypistats failed or
        # returned no last_month value, and we have a recent-enough cached
        # entry for this package, use it with the stale-age timestamp so
        # _render_row can surface the cached number + "cached Nh ago" tag.
        if row["pypi_downloads_month"] is None and row["pypi_name"] in dl_cache:
            cached = dl_cache[row["pypi_name"]]
            try:
                fetched_at = datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
                if age_hours <= DL_CACHE_STALE_HOURS:
                    row["pypi_downloads_month"] = cached["last_month"]
                    row["pypi_downloads_cached_at"] = cached["fetched_at"]
            except (KeyError, ValueError, TypeError):
                pass  # Malformed cache entry — skip stale fallback, leave pypi_downloads_month as-is

        # R89-60f Feature 3: sparkline 7-day SVG. Fetches pypistats overall
        # endpoint (with cache; cold fetch adds PYPISTATS_INTERCALL_DELAY
        # to respect rate limit). SVG embedded inline — no external assets.
        sparkline_vals = _fetch_sparkline_data(row["pypi_name"], dl_cache)
        row["sparkline_svg"] = _sparkline_svg(sparkline_vals)

    if row["gh_repo"]:
        try:
            repo_info = _fetch_json(f"https://api.github.com/repos/{row['gh_repo']}", accept_404=True)
            if repo_info:
                row["gh_stars"] = repo_info.get("stargazers_count")
                row["gh_forks"] = repo_info.get("forks_count")
                row["gh_pushed_at"] = repo_info.get("pushed_at")
                row["gh_description"] = repo_info.get("description")
                row["gh_html_url"] = repo_info.get("html_url")
                license_info = repo_info.get("license") or {}
                row["gh_license_spdx"] = license_info.get("spdx_id") if isinstance(license_info, dict) else None
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"github-repo: {exc.__class__.__name__}")

        try:
            release = _fetch_json(f"https://api.github.com/repos/{row['gh_repo']}/releases/latest", accept_404=True)
            if release:
                row["gh_release_tag"] = _normalize_version(release.get("tag_name", ""))
                row["gh_release_date"] = release.get("published_at")
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"github-release: {exc.__class__.__name__}")

        # R89-18a fix #1: Open CodeQL alert count.
        #
        # Empirically (2026-05-26 ground truth via gh api): the
        # public code-scanning/alerts endpoint returns HTTP 401 for
        # all WRG-11 repos when called anonymously — the docstring
        # comment about "public alerts work anonymously" was wishful
        # thinking, GitHub requires auth even for public-visibility
        # repos. With GH_AUTH_TOKEN threaded in, the same endpoint
        # returns real numbers (e.g. wrg-mcp-server has 1 open alert).
        #
        # Treat 401/403/404 as "no signal" (display "?") rather than
        # a hard error: token may be missing entirely (anonymous
        # fallback), or scoped to a subset of repos, or the repo
        # may have no CodeQL analysis configured yet (404 = "no
        # analysis found", common for newly-shipped repos).
        try:
            alerts = _fetch_json(
                f"https://api.github.com/repos/{row['gh_repo']}/code-scanning/alerts?state=open&per_page=100",
                accept_404=True,
                auth_token=GH_AUTH_TOKEN,
            )
            if alerts is not None and isinstance(alerts, list):
                row["gh_codeql_open"] = len(alerts)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                # Auth missing / insufficient scope / private alerts. "?".
                pass
            else:
                row["errors"].append(f"github-codeql: HTTP{exc.code}")
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(f"github-codeql: {exc.__class__.__name__}")

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
.alert-zero { color: #1a7f37; font-weight: 600; }
.alert-some { color: #cf222e; font-weight: 600; }
.footer { color: #6e7781; font-size: 0.85em; margin-top: 3em; border-top: 1px solid #eaeef2; padding-top: 1em; }
.footer a { color: #0969da; }
.metric { font-variant-numeric: tabular-nums; }
.license-chip {
  display: inline-block;
  padding: 0.05em 0.5em;
  margin-left: 0.4em;
  background: #ddf4ff;
  color: #0969da;
  border-radius: 1em;
  font-size: 0.72em;
  font-weight: 600;
  vertical-align: middle;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
/* Marketplace channel chips. Distinct per-channel colours so visitors
   associate chip-colour with destination at a glance after one scan. */
.channel-chip {
  display: inline-block;
  padding: 0.05em 0.5em;
  margin-left: 0.3em;
  border-radius: 1em;
  font-size: 0.72em;
  font-weight: 600;
  vertical-align: middle;
}
.channel-chip.ch-pypi              { background: #fff5d0; color: #7a5c00; }
.channel-chip.ch-github            { background: #eaeef2; color: #57606a; }
.channel-chip.ch-glama             { background: #e6f5e6; color: #1a7f37; }
.channel-chip.ch-anthropic         { background: #f5e6ff; color: #6f42c1; }
.channel-chip.ch-anthropic-pending { background: #f5e6ff; color: #8250df; opacity: 0.7; font-style: italic; }
.channel-chip.ch-docker            { background: #ddebff; color: #0969da; }
.channel-chip.ch-skills            { background: #fff0e6; color: #bc4c00; }
.channel-chip.ch-mcp-registry      { background: #d0f0e8; color: #0a6860; }
.channel-chip.ch-other             { background: #f6f8fa; color: #57606a; }
/* Stale-cache indicator on download numbers.
   Small, muted, not alarming — the number is still real, just last-known. */
.cached-tag {
  color: #8c959f;
  font-size: 0.7em;
  font-weight: 400;
  font-style: italic;
  margin-left: 0.3em;
}
/* Totals row (tfoot). Slightly bolder + bg accent
   to separate ecosystem-level aggregate from per-package rows. */
tfoot tr.totals td       { background: #f6f8fa; border-top: 2px solid #d0d7de; padding-top: 0.8em; padding-bottom: 0.8em; }
tfoot tr.totals strong   { font-size: 1.0em; }
tfoot tr.totals .totals-sub { color: #6e7781; font-size: 0.78em; font-weight: 400; margin-left: 0.3em; }
/* Test-coverage % column. Green/amber/red thresholds.
   Glama score rendered mono so the A/A/B grade letters align cleanly. */
.cov-high  { color: #1a7f37; font-weight: 600; font-variant-numeric: tabular-nums; }
.cov-mid   { color: #9a6700; font-weight: 600; font-variant-numeric: tabular-nums; }
.cov-low   { color: #cf222e; font-weight: 600; font-variant-numeric: tabular-nums; }
.glama-score { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.88em; }
/* Search/filter bar + mobile table scroll.
   Vanilla JS progressively enhances; table is fully readable without JS. */
.filter-bar { display: flex; gap: 0.6em; margin: 0.6em 0 0.4em; flex-wrap: wrap; align-items: center; }
.filter-bar input, .filter-bar select { padding: 0.35em 0.6em; border: 1px solid #d0d7de; border-radius: 6px; font-size: 0.9em; font-family: inherit; background: #fff; }
.filter-bar input { min-width: 180px; flex: 1 1 180px; }
.filter-bar select { min-width: 160px; }
.no-match { display: none; text-align: center; color: #57606a; font-size: 0.9em; padding: 1em 0; }
.table-wrapper { overflow-x: auto; -webkit-overflow-scrolling: touch; }
@media (max-width: 768px) {
  body { padding: 0 0.5em; }
  th, td { padding: 0.4em 0.5em; font-size: 0.85em; }
}
/* Brand + narrative section styles.
   No email-capture / upsell; informational links only. */
.section-heading { font-size: 1em; font-weight: 600; margin-top: 2em; margin-bottom: 0.5em; color: #24292f; border-bottom: 1px solid #eaeef2; padding-bottom: 0.3em; }
/* Marketplace channel matrix (Section 1) */
.ch-matrix th, .ch-matrix td { font-size: 0.85em; }
.ch-present { color: #1a7f37; font-weight: 600; }
.ch-pending { color: #9a6700; font-style: italic; }
.ch-absent  { color: #8c959f; }
/* Milestone banner (Section 2) — muted info strip, not marketing. */
.milestone-banner { background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; padding: 0.65em 1em; margin: 0.8em 0 0.4em; font-size: 0.87em; }
.milestone-banner strong { color: #0550ae; }
.milestone-banner ul { margin: 0.3em 0 0; padding-left: 1.2em; }
.milestone-banner li { margin: 0.15em 0; color: #24292f; }
/* Info-grid: flex row of cards for Sections 3/4/5 */
.info-grid { display: flex; flex-wrap: wrap; gap: 1em; margin-top: 1.5em; }
.info-card { flex: 1; min-width: 260px; border: 1px solid #d0d7de; border-radius: 6px; padding: 0.9em 1em; background: #f6f8fa; }
.info-card h3 { margin: 0 0 0.5em; font-size: 0.88em; font-weight: 600; color: #24292f; }
.info-card ul { margin: 0; padding-left: 1.2em; font-size: 0.83em; }
.info-card li { margin: 0.2em 0; color: #57606a; }
.info-card p { font-size: 0.85em; margin: 0.3em 0; color: #57606a; }
.info-card a { color: #0969da; }
/* DF CTA link (Section 3) */
.cta-link { display: inline-block; margin-top: 0.5em; color: #0969da; font-weight: 600; text-decoration: none; font-size: 0.88em; }
.cta-link:hover { text-decoration: underline; }
/* Vendor chips in disclosure chain (Section 5) */
.vendor-chain { font-size: 0.83em; color: #57606a; margin: 0.3em 0; line-height: 2.0; word-break: break-word; }
.vendor-chip { display: inline-block; background: #eaeef2; border-radius: 3px; padding: 0 0.35em; margin: 0.05em 0.1em; font-size: 0.9em; color: #24292f; white-space: nowrap; }
/* Sortable column headers — sort direction indicator. */
th.sortable::after { content: ' \2195'; color: #8c959f; font-size: 0.8em; }
th.sortable[data-sort-dir=asc]::after { content: ' \2191'; color: #0969da; }
th.sortable[data-sort-dir=desc]::after { content: ' \2193'; color: #0969da; }
/* Stale > 24h banner (JS-injected when body.data-generated-at is old).
   Surfaces stale data explicitly rather than silently showing old numbers. */
.stale-banner { background: #fff8c5; border: 1px solid #d4a72c; border-radius: 6px; padding: 0.6em 1em; margin: 0.6em 0; font-size: 0.87em; color: #633d11; }
"""


def _render_row(row: dict[str, Any]) -> str:
    pypi = row["pypi_version"]
    gh = row["gh_release_tag"]
    # R89-18a fix #3: explicit "GH-ONLY" label for entries with null
    # pypi_name (Claude Code plugins, GitHub-only MCP servers). Avoids
    # the misleading "?" which suggests a fetch error — there is no
    # drift to check because there is no PyPI version to compare. Take
    # precedence over OK/DRIFT/? branches below.
    if not row["pypi_name"]:
        status_html = '<span class="muted">GH-ONLY</span>'
    elif pypi and gh and pypi == gh:
        status_html = '<span class="ok">OK</span>'
    elif row["drift"]:
        status_html = '<span class="drift">DRIFT</span>'
    elif row["errors"]:
        status_html = '<span class="muted">?</span>'
    else:
        status_html = '<span class="muted">-</span>'

    name = html.escape(row["name"])
    url = row["gh_html_url"] or (f"https://github.com/{row['gh_repo']}" if row["gh_repo"] else "#")
    # R89-58f: description_override takes precedence over GitHub API description.
    # Used for wrg-sigma-rules (61 prod rules → 67 after R89-11d corpus add).
    desc_raw = row.get("description_override") or row["gh_description"] or row["pypi_summary"] or ""
    desc = html.escape(desc_raw)

    # R89-60f Feature 1: data-* attrs for client-side search/filter.
    # data-category = comma-separated category tags from sentry-targets.json.
    cats_attr = html.escape(",".join(row.get("categories") or []))

    name_cell = f'<span class="pkg-name"><a href="{html.escape(url)}">{name}</a></span>'
    if row["gh_license_spdx"]:
        name_cell += f'<span class="license-chip">{html.escape(row["gh_license_spdx"])}</span>'
    # R89-18a enhancement B: marketplace channel chips next to license.
    # Surfaces multi-channel distribution (PyPI / Glama / Anthropic CC, etc.)
    # so visitors see WHERE each package ships from at a glance.
    for ch in row.get("channels") or []:
        chip_class, chip_label = _channel_chip(ch)
        name_cell += f'<span class="channel-chip {chip_class}">{html.escape(chip_label)}</span>'
    if desc:
        name_cell += f'<div class="pkg-desc">{desc}</div>'

    codeql_open = row["gh_codeql_open"]
    if codeql_open is None:
        codeql_html = '<span class="muted">?</span>'
    elif codeql_open == 0:
        codeql_html = '<span class="alert-zero">0</span>'
    else:
        codeql_html = f'<span class="alert-some">{codeql_open}</span>'

    # R89-58f: test-coverage cell (static from config/sentry-targets.json).
    # Thresholds: ≥90% green, ≥75% amber, <75% red. "n/a" for corpus/GitHub-only
    # repos where coverage % is not meaningful (e.g. wrg-sigma-rules rule corpus).
    cov = row.get("coverage_pct")
    if cov is None:
        cov_html = '<span class="muted">n/a</span>'
    elif cov >= 90:
        cov_html = f'<span class="cov-high">{cov}%</span>'
    elif cov >= 75:
        cov_html = f'<span class="cov-mid">{cov}%</span>'
    else:
        cov_html = f'<span class="cov-low">{cov}%</span>'

    # R89-58f: Glama catalog score cell (static "A/A/B" from config).
    # Rendered monospace so the grade letters line up across rows.
    glama = row.get("glama_score")
    if glama:
        glama_html = f'<span class="glama-score">{html.escape(str(glama))}</span>'
    else:
        glama_html = '<span class="muted">-</span>'

    # R89-18a enhancement C: cached DL fallback indicator.
    # When pypistats failed THIS run but a cache hit served the number,
    # render '<value> <small>cached Nh ago</small>' so the data is
    # transparent (no silent staleness) but visible (no "?" hole).
    dl_int = _fmt_int(row["pypi_downloads_month"])
    if row.get("pypi_downloads_cached_at") and row["pypi_downloads_month"] is not None:
        age = _cache_age_label(row["pypi_downloads_cached_at"])
        dl_cell = f'{dl_int} <span class="cached-tag">{html.escape(age)}</span>'
    else:
        dl_cell = dl_int

    # R89-60f Feature 3: prepend sparkline SVG to downloads cell (inline, no JS needed).
    sparkline = row.get("sparkline_svg") or ""
    if sparkline:
        dl_cell = f'{sparkline}&thinsp;{dl_cell}'

    # R89-60f Feature 2: data-val for numeric sort on sortable columns.
    # Only emitted when value is known; unknown cells sort to bottom (JS NaN→∞).
    dl_raw = row["pypi_downloads_month"]
    dl_val = f' data-val="{dl_raw}"' if dl_raw is not None else ""
    stars_val = f' data-val="{row["gh_stars"]}"' if row["gh_stars"] is not None else ""
    forks_val = f' data-val="{row["gh_forks"]}"' if row["gh_forks"] is not None else ""
    release_val = f' data-val="{_date_to_days(row["gh_release_date"])}"' if row["gh_release_date"] else ""
    commit_val = f' data-val="{_date_to_days(row["gh_pushed_at"])}"' if row["gh_pushed_at"] else ""

    return (
        # R89-60f Feature 1: data-category/name/desc for search+filter JS.
        f'<tr data-category="{cats_attr}" data-name="{html.escape(row["name"])}" data-desc="{html.escape(desc_raw)}">'
        f"<td>{name_cell}</td>"
        f'<td class="ver">{html.escape(pypi) if pypi else "<span class=\"muted\">-</span>"}</td>'
        f'<td class="ver">{html.escape(gh) if gh else "<span class=\"muted\">-</span>"}</td>'
        f"<td>{status_html}</td>"
        f'<td class="metric">{codeql_html}</td>'
        f'<td class="metric">{cov_html}</td>'    # R89-58f coverage col
        f'<td>{glama_html}</td>'                  # R89-58f Glama col
        f'<td class="metric"{dl_val}>{dl_cell}</td>'
        f'<td class="metric"{stars_val}>{_fmt_int(row["gh_stars"])}</td>'
        f'<td class="metric"{forks_val}>{_fmt_int(row["gh_forks"])}</td>'
        f'<td{release_val}>{html.escape(_fmt_relative_date(row["gh_release_date"]))}</td>'
        f'<td{commit_val}>{html.escape(_fmt_relative_date(row["gh_pushed_at"]))}</td>'
        "</tr>"
    )


def _channel_chip(channel: str) -> tuple[str, str]:
    """Map a channel id to (CSS-class-suffix, visible-label). Unknown channels
    render with the generic 'ch-other' class so they still display."""
    table = {
        "pypi":                   ("ch-pypi", "PyPI"),
        "github":                 ("ch-github", "GitHub"),
        "glama":                  ("ch-glama", "Glama"),
        "anthropic_cc":           ("ch-anthropic", "Anthropic CC"),
        "anthropic_cc_pending":   ("ch-anthropic-pending", "Anthropic CC ⏳"),
        "docker_mcp_catalog":     ("ch-docker", "Docker MCP"),
        "skills_sh":              ("ch-skills", "skills.sh"),
        "mcp_registry":           ("ch-mcp-registry", "MCP Registry"),
    }
    return table.get(channel, ("ch-other", channel.replace("_", " ")))


# ============================================================
# R89-59f Phase 2: static brand + narrative sections.
# Brief: .agents/inbox/F/from-A/2026-05-27-2342-r89-59f-portfolio-phase-2-brand-narrative.md
# Anti-spam discipline: informational links only; no upsell / email-capture.
# All sections hardcoded (brief Q&A F karar: static this wave; dynamic Phase 3 candidate).
# ============================================================

# --- Section 2: 2026-05-27 milestone banner ---------------------------------
# Hardcoded (brief Q1 reco: static this wave; dynamic Phase 3 via AGENTS.md parse).
# Public-facing language: internal sprint codes translated to technical substance.
_MILESTONE_BANNER = """\
<div class="milestone-banner">
  <strong>&#x1F393; Recent milestones (2026-05-27)</strong>
  <ul>
    <li>Sigma detection methodology validated &#x2014; 0 / 67 rule false-positives across all 10 MITRE ATT&amp;CK categories, confirmed over three independent test cycles</li>
    <li>Single-source documentation architecture &#x2014; one canonical topology definition eliminates roster drift across the docs</li>
    <li>Five reusable agent helpers shipped &#x2014; inbox triage, OPSEC/PII scan, brief validation, cross-repo PR sweep, template generation</li>
    <li>Research catalog &#x2014; 33 documented threat &amp; defense patterns from field analysis, including a convergent multi-vendor supply-chain risk chain</li>
  </ul>
  <strong>&#x1F4E6; 2026-05-28 milestones</strong>
  <ul>
    <li>wrg-mcp-server now listed on the MCP Registry, Glama, and awesome-mcp-servers (3 of 5 target distribution channels live)</li>
    <li>arastirma-ussu: 8 security fixes shipped &#x2014; 3 critical (cache race conditions) + 5 high-severity (error-handling + prompt-injection defense)</li>
    <li>Research pattern catalog grew to 35 documented threat &amp; defense patterns</li>
    <li>New detection pattern formalized &#x2014; &#x201C;silent semantic violation&#x201D;: systems that pass infrastructure/auth checks while violating intent (phishing via account-recovery flows; grey-market AI API supply chains)</li>
    <li>A recurring cross-vendor threat pattern is now tracked across 18 documented field cases</li>
  </ul>
</div>"""


# --- Section 3: Detection Frontier newsletter CTA --------------------------
# Anti-spam discipline (Pattern 35 sister): no email-capture inline; subscribe link only.
# URL: https://detection-frontier.kit.com/subscribe (Kit free tier, detectionfrontier@proton.me)
_DF_CTA_HTML = """\
  <div class="info-card">
    <h3>&#x1F4F0; Detection Frontier</h3>
    <p>AI threat research newsletter &#x2014; bot-detection, sigma methodology, LLM security disclosures.
    Written from the WRG-11 field research stack.</p>
    <a class="cta-link" href="https://detection-frontier.kit.com/subscribe">Subscribe &#x2197;</a>
    <p style="margin-top:0.4em;font-size:0.78em;color:#8c959f;">No tracking &middot; free &middot; ~weekly</p>
  </div>"""


# --- Section 4: Subagent class status box ----------------------------------
# 5 LIVE subagents post-AGENTS.md §15.48 FORMAL SEAL (2026-05-27).
# Source: docs/agents/_topology.md canonical roster.
# Hardcoded (brief Q4 F karar: stable 5-vaka FORMAL SEAL; dynamic Phase 3 candidate).
_SUBAGENT_BOX_HTML = """\
  <div class="info-card">
    <h3>&#x1F916; Reusable agent helpers</h3>
    <ul>
      <li>&#x2705; <strong>inbox-triager</strong> &#x2014; async dispatch on session-start</li>
      <li>&#x2705; <strong>cross-repo-pr-sweeper</strong> &#x2014; portfolio PR enumerate</li>
      <li>&#x2705; <strong>opsec-pii-scanner</strong> &#x2014; Tier 1/2/3 PII + false-flag matrix</li>
      <li>&#x2705; <strong>brief-validator</strong> &#x2014; SB-57 spec-drift mitigation</li>
      <li>&#x2705; <strong>brief-template-generator</strong> &#x2014; frontmatter discipline</li>
    </ul>
    <p style="margin-top:0.5em;font-size:0.78em;color:#8c959f;">5 helpers &middot; shared across the agent workflow</p>
  </div>"""


# --- Section 5: 16-vendor responsible disclosure chain --------------------
# R60→R82 sprints. 15 vendors in original brief; CrewAI confirmed 16th per §15.37.
# Anthropic Project Glasswing added 2026-05-28 (SB-86 chain count fix; total now 16).
# Link target: WRG-11/WinstonRedGuard monorepo (public research notes).
# HTML entities used for arrows to avoid encoding issues in static page.
_DISCLOSURE_CHAIN_HTML = """\
  <div class="info-card">
    <h3>&#x1F510; Active disclosure chain <span style="font-weight:400;color:#57606a;font-size:0.85em">(16 vendors R60&#x2192;R82)</span></h3>
    <p class="vendor-chain">
      <span class="vendor-chip">Mullvad</span> &#x2192;
      <span class="vendor-chip">Mozilla</span> &#x2192;
      <span class="vendor-chip">Cisco</span> &#x2192;
      <span class="vendor-chip">Docker</span> &#x2192;
      <span class="vendor-chip">PostgreSQL</span> &#x2192;
      <span class="vendor-chip">Jenkins</span> &#x2192;
      <span class="vendor-chip">Exim</span> &#x2192;
      <span class="vendor-chip">PowerDNS</span> &#x2192;
      <span class="vendor-chip">OpenSSH</span> &#x2192;
      <span class="vendor-chip">Keycloak</span> &#x2192;
      <span class="vendor-chip">OpenClaw</span> &#x2192;
      <span class="vendor-chip">Kubernetes ingress&#x2011;nginx</span> &#x2192;
      <span class="vendor-chip">Microsoft Hyper&#x2011;V</span> &#x2192;
      <span class="vendor-chip">LangChain</span> &#x2192;
      <span class="vendor-chip">CrewAI</span> &#x2192;
      <span class="vendor-chip">Anthropic Project Glasswing</span>
    </p>
    <p><a href="https://github.com/WRG-11/WinstonRedGuard">Full chain &#x2197;</a>
    <span style="color:#8c959f;font-size:0.78em">&middot; responsible disclosure; CVE-ID data in research notes</span></p>
  </div>"""


# --- Section 1: MCP marketplace channel distribution (Pattern 45) ----------
_CHANNEL_SECTION_HTML = """\
<h2 class="section-heading">MCP marketplace distribution</h2>
<p style="font-size:0.85em;color:#57606a;margin:0.3em 0 0.8em;"><strong>wrg-sigma-rules</strong> is
the only sigma detection plugin submitted to the Anthropic Claude Code marketplace. Live on 3 of 5
target distribution channels (Glama, awesome-mcp-servers, MCP Registry); Docker MCP Catalog <a href="https://github.com/docker/mcp-registry/pull/3836" style="color:inherit">PR #3836</a> open; Anthropic CC listing pending. Verified 2026-05-28.</p>
<table class="ch-matrix">
  <thead>
    <tr>
      <th>Package</th>
      <th>Anthropic CC</th>
      <th>Glama</th>
      <th>awesome-mcp-servers</th>
      <th>MCP Registry</th>
      <th>Docker MCP Catalog</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>wrg-sigma-rules</td>
      <td class="ch-pending">&#x23F3; submitted</td>
      <td class="ch-present">&#x2705; <a href="https://glama.ai/mcp/servers/wrg-sigma-rules" style="color:inherit">A/A/B</a></td>
      <td class="ch-present">&#x2705; <a href="https://github.com/punkpeye/awesome-mcp-servers/pull/6905" style="color:inherit">PR #6905</a></td>
      <td class="ch-absent">&#x2014;</td>
      <td class="ch-absent">&#x2014;</td>
    </tr>
    <tr>
      <td>wrg-mcp-server</td>
      <td class="ch-absent">&#x2014;</td>
      <td class="ch-absent">&#x2014;</td>
      <td class="ch-absent">&#x2014;</td>
      <td class="ch-present">&#x2705; <a href="https://registry.modelcontextprotocol.io/v0/servers?search=WRG-11" style="color:inherit">v1.0.7</a></td>
      <td class="ch-pending">&#x23F3; <a href="https://github.com/docker/mcp-registry/pull/3836" style="color:inherit">PR #3836 OPEN</a></td>
    </tr>
    <tr><td>instinct</td><td colspan="5" class="ch-absent" style="font-size:0.82em;">PyPI + GitHub only</td></tr>
    <tr><td>arastirma-ussu</td><td colspan="5" class="ch-absent" style="font-size:0.82em;">GitHub only (MCP server; marketplaces not yet targeted)</td></tr>
    <tr><td>wrg-rule-lab</td><td colspan="5" class="ch-absent" style="font-size:0.82em;">PyPI + GitHub only (Python library)</td></tr>
    <tr><td>wrg-devguard</td><td colspan="5" class="ch-absent" style="font-size:0.82em;">PyPI + GitHub only (CLI + GitHub Action)</td></tr>
  </tbody>
</table>"""


# ============================================================
# R89-60f Phase 3: vanilla JS + filter bar.
# Brief: .agents/inbox/F/from-A/2026-05-27-2342-r89-60f-portfolio-phase-3-ux-ops.md
# Pattern 47 reuse>new strict: minimal client-side; no framework deps.
# IIFE-wrapped; activates via data-* attrs set at generation time.
# Features 1 (search/filter) + 2 (sortable columns) + 4 (stale banner)
# all live in _JS so they share one <script> tag.
# ============================================================

# --- Filter bar HTML (Feature 1) ----------------------------------------
# Category values must match `categories` arrays in sentry-targets.json.
_FILTER_BAR_HTML = """\
<div class="filter-bar">
  <input type="text" id="pkg-search" placeholder="Search packages…" aria-label="Search packages" />
  <select id="cat-filter" aria-label="Filter by category">
    <option value="">All categories</option>
    <option value="security">Security</option>
    <option value="sigma">Sigma / Detection</option>
    <option value="mcp">MCP</option>
    <option value="ai">AI</option>
    <option value="devops">DevOps</option>
    <option value="research">Research</option>
    <option value="memory">Memory</option>
  </select>
</div>"""


# --- All vanilla JS (Features 1 + 2 + 4) --------------------------------
# Single IIFE so no globals leak; data-* attributes on <tr>/<th>/<body> are
# the only contract between the Python generator and this runtime code.
_JS = """\
(function(){
  // --- Feature 1: search + category filter ---
  var search=document.getElementById('pkg-search');
  var catSel=document.getElementById('cat-filter');
  var tbody=document.querySelector('table tbody');
  var allRows=tbody?[].slice.call(tbody.querySelectorAll('tr')):[];
  var noMatch=document.getElementById('filter-no-match');
  function applyFilter(){
    var q=search?search.value.toLowerCase():'';
    var cat=catSel?catSel.value:'';
    var vis=0;
    allRows.forEach(function(tr){
      var nm=(tr.dataset.name||'').toLowerCase();
      var dc=(tr.dataset.desc||'').toLowerCase();
      var cats=(tr.dataset.category||'').split(',');
      var mQ=!q||nm.indexOf(q)!==-1||dc.indexOf(q)!==-1;
      var mC=!cat||cats.indexOf(cat)!==-1;
      tr.style.display=(mQ&&mC)?'':'none';
      if(mQ&&mC)vis++;
    });
    if(noMatch)noMatch.style.display=vis===0?'block':'none';
  }
  if(search)search.addEventListener('input',applyFilter);
  if(catSel)catSel.addEventListener('change',applyFilter);

  // --- Feature 2: sortable columns ---
  var sortCol=-1,sortDir=1;
  var ths=[].slice.call(document.querySelectorAll('th.sortable'));
  ths.forEach(function(th){
    th.style.cursor='pointer';
    th.title='Click to sort';
    th.addEventListener('click',function(){
      var c=parseInt(th.dataset.col,10);
      if(sortCol===c){sortDir=-sortDir;}else{sortCol=c;sortDir=1;}
      ths.forEach(function(t){t.removeAttribute('data-sort-dir');});
      th.setAttribute('data-sort-dir',sortDir===1?'asc':'desc');
      if(!tbody)return;
      var rs=[].slice.call(tbody.querySelectorAll('tr'));
      rs.sort(function(a,b){
        var ac=a.cells[c],bc=b.cells[c];
        var av=ac&&ac.dataset?parseFloat(ac.dataset.val):NaN;
        var bv=bc&&bc.dataset?parseFloat(bc.dataset.val):NaN;
        if(isNaN(av))av=Infinity;if(isNaN(bv))bv=Infinity;
        return (av-bv)*sortDir;
      });
      rs.forEach(function(r){tbody.appendChild(r);});
    });
  });

  // --- Feature 4: stale > 24h banner ---
  var genAt=document.body&&document.body.dataset.generatedAt;
  if(genAt){
    var ageH=(Date.now()-new Date(genAt).getTime())/3600000;
    if(ageH>24){
      var b=document.createElement('div');
      b.className='stale-banner';
      b.textContent='⚠️ Dashboard data is '+Math.round(ageH)+'h old — GHA cron may be paused (billing gate). Run dashboard.py locally to refresh.';
      var h1=document.querySelector('h1');
      if(h1&&h1.parentNode)h1.parentNode.insertBefore(b,h1.nextSibling);
    }
  }
})();"""


def _render_totals_row(rows: list[dict[str, Any]]) -> str:
    """R89-18a enhancement A: aggregate totals as a tfoot row.
    Renders the single-line scale signal — package count, total
    downloads, total stars/forks, total open alerts — so a visitor
    sees ecosystem-level numbers without manually adding up cells."""
    total_packages = len(rows)
    total_dl = sum(r["pypi_downloads_month"] or 0 for r in rows)
    total_stars = sum(r["gh_stars"] or 0 for r in rows)
    total_forks = sum(r["gh_forks"] or 0 for r in rows)
    total_alerts = sum(r["gh_codeql_open"] or 0 for r in rows if r["gh_codeql_open"] is not None)
    alerts_known = sum(1 for r in rows if r["gh_codeql_open"] is not None)
    pypi_packages = sum(1 for r in rows if r["pypi_name"])
    # Alert-known coverage badge: how many of the targets the CodeQL
    # column actually reflects (rest are "?" — no CodeQL setup yet or
    # alert-read auth missing). Honest signal vs claiming 0/5.
    alerts_cell_class = "alert-zero" if total_alerts == 0 else "alert-some"
    return (
        '<tr class="totals">'
        f'<td><strong>TOTAL — {total_packages} packages</strong>'
        f' <span class="totals-sub">({pypi_packages} on PyPI, {total_packages - pypi_packages} GitHub-only)</span></td>'
        '<td class="ver"><span class="muted">-</span></td>'  # PyPI col
        '<td class="ver"><span class="muted">-</span></td>'  # GH col
        '<td><span class="muted">-</span></td>'              # Status col
        f'<td class="metric"><span class="{alerts_cell_class}">{total_alerts}</span>'
        f' <span class="totals-sub">/ {alerts_known} scanned</span></td>'
        '<td class="metric"><span class="muted">-</span></td>'  # Coverage col (R89-58f)
        '<td><span class="muted">-</span></td>'                  # Glama col (R89-58f)
        f'<td class="metric"><strong>{_fmt_int(total_dl)}</strong></td>'
        f'<td class="metric"><strong>{_fmt_int(total_stars)}</strong></td>'
        f'<td class="metric"><strong>{_fmt_int(total_forks)}</strong></td>'
        '<td><span class="muted">-</span></td>'              # Last release col
        '<td><span class="muted">-</span></td>'              # Last commit col
        '</tr>'
    )


def _render_html(rows: list[dict[str, Any]], generated_at: datetime) -> str:
    table_rows = "\n      ".join(_render_row(r) for r in rows)
    totals_row = _render_totals_row(rows)  # R89-18a enhancement A
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
<title>WRG-11 Portfolio &#x2014; open-source AI/LLM security tooling</title>
<meta name="description" content="Open-source security tooling for AI/LLM defense, detection engineering, threat intelligence, and OSINT. Sigma detection rules, MCP server, dev policy scanner &#x2014; zero-dependency Python, MIT licensed." />
<link rel="canonical" href="https://wrg-11.github.io/wrg-portfolio/" />
<meta name="theme-color" content="#0969da" />
<link rel="icon" href="https://github.com/WRG-11.png" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="WRG-11" />
<meta property="og:title" content="WRG-11 Portfolio &#x2014; open-source AI/LLM security tooling" />
<meta property="og:description" content="Sigma detection rules, MCP server, dev policy scanner, threat-intel + OSINT. Zero-dependency Python, MIT licensed." />
<meta property="og:url" content="https://wrg-11.github.io/wrg-portfolio/" />
<meta property="og:image" content="https://github.com/WRG-11.png" />
<meta name="twitter:card" content="summary" />
<meta name="twitter:title" content="WRG-11 Portfolio &#x2014; open-source AI/LLM security tooling" />
<meta name="twitter:description" content="Sigma detection rules, MCP server, dev policy scanner, threat-intel + OSINT. Zero-dependency Python, MIT licensed." />
<meta name="twitter:image" content="https://github.com/WRG-11.png" />
<style>{_CSS}</style>
</head>
<body data-generated-at="{generated_at.isoformat()}">
  <h1>WRG-11 Portfolio</h1>
  <p class="lede">Open-source security tooling for AI/LLM defense, detection
  engineering, threat intelligence, and OSINT. Zero-dependency Python where
  it makes sense; MIT licensed across the ecosystem.</p>
  {_MILESTONE_BANNER}
  <p><strong>Snapshot:</strong> {summary}</p>

  {_FILTER_BAR_HTML}
  <div class="table-wrapper">
  <table>
    <thead>
      <tr>
        <th>Package</th>
        <th>PyPI</th>
        <th>GH Release</th>
        <th>Status</th>
        <th>CodeQL alerts</th>
        <th>Coverage</th>
        <th>Glama</th>
        <th class="sortable" data-col="7">Downloads (30d)</th>
        <th class="sortable" data-col="8">Stars</th>
        <th class="sortable" data-col="9">Forks</th>
        <th class="sortable" data-col="10">Last release</th>
        <th class="sortable" data-col="11">Last commit</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
    <tfoot>
      {totals_row}
    </tfoot>
  </table>
  <p id="filter-no-match" class="no-match">No packages match your filter.</p>
  </div>
  {_CHANNEL_SECTION_HTML}
  <div class="info-grid">
  {_DF_CTA_HTML}
  {_SUBAGENT_BOX_HTML}
  {_DISCLOSURE_CHAIN_HTML}
  </div>

  <p class="footer">
    Generated {generated_at.strftime("%Y-%m-%d %H:%M UTC")} by
    <a href="https://github.com/WRG-11/wrg-portfolio">wrg-portfolio</a>
    (version-sentry sister). Daily auto-refresh via GitHub Actions cron.
    Data sources: pypi.org, pypistats.org, api.github.com. No tracking,
    minimal vanilla JS, no external assets.
  </p>
  <script>{_JS}</script>
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

    # R89-18a enhancement C: load DL cache before collection so each
    # target can fall back to a cached pypistats response when the
    # live API fails (typically 429 on shared GHA runner IPs).
    dl_cache = _load_dl_cache(DL_CACHE_PATH)
    rows = [_collect_target(t, dl_cache=dl_cache) for t in targets]
    # Persist (possibly updated) cache so next run starts hot.
    _save_dl_cache(DL_CACHE_PATH, dl_cache)
    generated_at = datetime.now(timezone.utc)
    html_doc = _render_html(rows, generated_at)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_doc, encoding="utf-8")

    failed = sum(1 for r in rows if r["errors"])
    cached_fallbacks = sum(1 for r in rows if r.get("pypi_downloads_cached_at"))
    suffix = f" ({cached_fallbacks} DL from cache)" if cached_fallbacks else ""
    print(f"[dashboard] wrote {args.out} ({len(rows)} rows, {failed} with query errors){suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
