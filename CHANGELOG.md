# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Hygiene boilerplate: `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`
- Dependabot config (`.github/dependabot.yml`): weekly GitHub Actions + pip update PRs
- Issue templates (`bug_report.md`, `feature_request.md`) and PR template
- CodeQL self-scan workflow (`.github/workflows/codeql.yml`): weekly + push trigger
- wrg-devguard self-scan workflow (`.github/workflows/self-scan.yml`): weekly + push trigger
- Dashboard: `open_codeql_alerts` column (per-repo open CodeQL alert count via GitHub API)
- README: CodeQL + self-scan badges; "What you'll see" dashboard preview section

### Changed
- README rewrite: fresh-visitor-friendly disciplinary 6-section template (tagline + Why + Use cases + How it compares + When to reach + Where it loses today)

## [0.1.0] - 2026-05-22

### Added
- `scripts/version_sentry.py` (stdlib only): daily PyPI vs GitHub Release tag drift check
- `scripts/dashboard.py` (stdlib only): single-page HTML snapshot of every WRG-11 package
- `config/sentry-targets.json`: list of `(pypi_name, gh_repo)` tuples to watch
- `.github/workflows/version_sentry.yml`: daily 06:00 UTC cron + `workflow_dispatch`
- `.github/workflows/dashboard.yml`: daily 07:00 UTC cron + commit-if-changed
- GitHub Pages live dashboard at https://wrg-11.github.io/wrg-portfolio/
- MIT LICENSE
