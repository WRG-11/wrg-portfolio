# wrg-portfolio

[![Pages](https://img.shields.io/badge/Pages-live-3b82f6?style=flat-square)](https://wrg-11.github.io/wrg-portfolio/)
[![CI](https://img.shields.io/badge/version--sentry-daily%2006%3A00%20UTC-34D058?style=flat-square)](https://github.com/WRG-11/wrg-portfolio/actions/workflows/version_sentry.yml)
[![Dashboard](https://img.shields.io/badge/dashboard-daily%2007%3A00%20UTC-34D058?style=flat-square)](https://github.com/WRG-11/wrg-portfolio/actions/workflows/dashboard.yml)
[![CodeQL](https://github.com/WRG-11/wrg-portfolio/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/WRG-11/wrg-portfolio/actions/workflows/codeql.yml)
[![self-scan](https://github.com/WRG-11/wrg-portfolio/actions/workflows/self-scan.yml/badge.svg?branch=main)](https://github.com/WRG-11/wrg-portfolio/actions/workflows/self-scan.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Self-hosted health monitor for the WRG-11 open-source ecosystem. Zero external services — daily GitHub Actions cron + stdlib Python + a self-contained HTML dashboard.**

Live dashboard: **[https://wrg-11.github.io/wrg-portfolio/](https://wrg-11.github.io/wrg-portfolio/)**

## What you'll see on the dashboard

A single self-contained HTML page with one row per WRG-11 package. Columns:

| Column | What it shows |
|---|---|
| **Package** | Package name + GitHub link + license SPDX chip + short description |
| **PyPI** | Latest published version on PyPI |
| **GH Release** | Latest tag from GitHub Releases |
| **Status** | `OK` (PyPI = GH Release) / `DRIFT` (mismatch) / `?` (query error) |
| **CodeQL alerts** | Count of open CodeQL security alerts (`0` green; `N` red; `?` private/disabled) |
| **Downloads (30d)** | Monthly PyPI download count (pypistats.org) |
| **Stars / Forks** | GitHub repo metrics |
| **Last release / Last commit** | Relative dates ("2 days ago", "1 month ago") |

Snapshot summary at the top: `N OK | N DRIFT | N with query errors`. Footer notes the generation timestamp and the data sources (pypi.org, pypistats.org, api.github.com). No JavaScript, no fonts, no tracking pixels — the whole page is one ~10KB `index.html`.

## Why this exists

Maintaining a multi-package open-source ecosystem (5+ PyPI packages, sister GitHub repos) creates recurring drift problems:

- **PyPI version vs GitHub Release tag drift** — you `pip install` a package, but the GitHub Release doesn't match (forgot to tag, or vice versa)
- **Scattered package health visibility** — checking downloads/stars/last-commit across 5+ repos requires 5+ browser tabs
- **No single "is everything healthy?" snapshot** — needs a tool, not a manual ritual

`wrg-portfolio` is the meta-repo that solves both: a daily sentry that catches version drift + a self-contained HTML dashboard that aggregates every WRG-11 package into one page. No SaaS, no dashboards-as-a-service, no proprietary analytics — everything lives in this repo and runs on your own GitHub Actions minutes.

## Use cases

- **Cross-portfolio health check** — open one page, see every WRG-11 package's PyPI version + GitHub Release + downloads + stars + last-commit-age at a glance
- **Drift catch before it ships** — sentry opens a GitHub Issue automatically when PyPI ≠ GH Release for any tracked package (CI cron 06:00 UTC daily)
- **Replicable monitoring template** — fork this repo, replace `config/sentry-targets.json` with your own packages, get the same dashboard for any GitHub org with zero infra
- **Zero-dep / zero-SaaS principle showcase** — proves you can run real ecosystem monitoring on GitHub Actions free tier alone (no datadog, no honeycomb, no buy-vs-build trade-off)

## Quick start

Browse the live dashboard: **[wrg-11.github.io/wrg-portfolio](https://wrg-11.github.io/wrg-portfolio/)**

Or fork + reuse for your own org:

```bash
git clone https://github.com/WRG-11/wrg-portfolio.git
cd wrg-portfolio

# Edit the targets list
nano config/sentry-targets.json    # add your (pypi_name, gh_repo) tuples

# Local sentry run (no GitHub auth required for read-only check)
python scripts/version_sentry.py --config config/sentry-targets.json --json-out sentry-report.json

# Local dashboard regeneration
python scripts/dashboard.py --config config/sentry-targets.json --out docs/index.html
```

Push to your fork, enable GitHub Pages (`Settings` → `Pages` → `Source: main branch /docs folder`), and the two scheduled workflows (`version_sentry.yml` + `dashboard.yml`) start running daily.

## Components

### version-sentry

Daily check that PyPI versions match the latest GitHub Release tag for each WRG-11 package shipped. When the two drift, the sentry opens a GitHub Issue and pings the operator.

| File | Purpose |
|---|---|
| `scripts/version_sentry.py` | The sentry itself (stdlib only: `urllib.request` + `json` + `subprocess` + `argparse` + `pathlib`) |
| `config/sentry-targets.json` | List of `(pypi_name, gh_repo)` tuples the sentry watches |
| `.github/workflows/version_sentry.yml` | Runs daily 06:00 UTC + manual `workflow_dispatch`. Uploads JSON report as artifact |

**Exit codes**: `0` = no drift / `1` = drift detected. Optional `--create-issue` flag opens a GitHub Issue when drift is found (CI uses this; local runs default to report-only).

### dashboard

Single-page HTML snapshot of every WRG-11 package: PyPI version, GitHub Release tag, drift status, monthly PyPI downloads, GitHub stars + forks, last-commit relative date. **No JavaScript, no fonts, no tracking pixels** — the whole page is one self-contained `index.html`.

| File | Purpose |
|---|---|
| `scripts/dashboard.py` | The generator (stdlib only) |
| `docs/index.html` | The rendered page (committed and served) |
| `.github/workflows/dashboard.yml` | Runs daily 07:00 UTC + manual `workflow_dispatch`. If rendered page differs from `main`, commits the new version as `github-actions[bot]`. Permissions: `contents: write` |

Served by GitHub Pages from `/docs` on `main`; live at [wrg-11.github.io/wrg-portfolio](https://wrg-11.github.io/wrg-portfolio/).

## How it compares

| Tool | Scope | Dependencies | Hosting | Best for |
|---|---|---|---|---|
| **wrg-portfolio** | PyPI-version drift + cross-repo metrics dashboard | Zero (stdlib only) | GitHub Actions + Pages (free tier) | Self-hosted single-org open-source ecosystem health |
| [Dependabot](https://github.com/dependabot) | Dependency updates | GitHub-native | GitHub-hosted | Per-repo dependency PRs |
| [Renovate](https://github.com/renovatebot/renovate) | Dependency updates + scheduled | Node + GitHub App | GitHub or self-hosted | Multi-language dep management |
| [PyPI Health Dashboard (custom)](https://pypistats.org/) | PyPI download stats | Web service | pypistats.org | One-package PyPI metrics |
| [Snyk / Mend](https://snyk.io/) | Vulnerability + license | SaaS subscription | Vendor cloud | Enterprise compliance |

## When to reach for wrg-portfolio (or fork it)

- You maintain 3+ Python packages on PyPI across one GitHub org and want one health page
- You want zero-SaaS / zero-dep ecosystem monitoring (free tier GitHub Actions only)
- You want a replicable, hackable template — not a vendor lock-in

## Where wrg-portfolio loses today (honest delta)

- **Single-org scope** — current code assumes one GitHub org's packages; multi-org support needs config schema extension
- **Python-only metrics** — PyPI download counts work for Python packages; npm/RubyGems/etc. need new fetchers
- **No alerting beyond GitHub Issue** — sentry opens an Issue but doesn't email/Slack/Discord (could add via existing Issue-watching channels)
- **Dashboard is static daily snapshot** — not real-time; for live metrics you need a different tool

## Roadmap

- **Marketplace presence tracker** — Anthropic Claude Code plugin directory + Glama.ai install/star snapshot
- **Mastodon / BlueSky publisher** — auto-post a one-line announcement when a new GitHub Release ships in any WRG-11 package (operator approval per post)
- **Multi-org config schema** — fork-friendly extension to monitor packages across multiple GitHub orgs
- **Dashboard expansion** — open-issues count + last-commit-age + Dependabot lag + CI status badge per repo

## Sister WRG-11 packages

The packages this repo monitors:

- [`instinct-mcp`](https://pypi.org/project/instinct-mcp/) — Self-learning memory for AI coding agents (MCP server)
- [`wrg-devguard`](https://pypi.org/project/wrg-devguard/) — Developer-first AI safety: prompt-policy lint + secret scanning + log scanning with PII detection
- [`wrg-mcp-server`](https://pypi.org/project/wrg-mcp-server/) — MCP bridge for the WinstonRedGuard monorepo (60+ security/threat-intel tools)
- [`wrg-rule-lab`](https://pypi.org/project/wrg-rule-lab/) — Local-first deterministic rule evaluation engine (zero-dep, stdlib-only)
- [`ai-security-toolkit`](https://github.com/WRG-11/ai-security-toolkit) — Offensive + defensive AI/LLM security tools, labs, CTF writeups, research

Built by [WRG-11](https://github.com/WRG-11).

## License

MIT — see [LICENSE](LICENSE).
