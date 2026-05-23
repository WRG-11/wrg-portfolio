# WRG-11 portfolio

Operations and automation for the WRG-11 open-source ecosystem.

Zero-dep Python stdlib + GitHub Actions. No external services, no
dashboards-as-a-service, no proprietary SaaS — everything lives in
this repo and runs in your own CI.

## Components

### version-sentry

Daily check that PyPI versions match the latest GitHub Release tag for
each WRG-11 package we ship. When the two drift (a PyPI bump was made
without a matching GitHub Release, or vice versa), the sentry opens a
GitHub Issue here and pings the operator.

- `scripts/version_sentry.py` — the sentry itself (stdlib only:
  urllib.request + json + subprocess + argparse + pathlib).
- `config/sentry-targets.json` — list of `(pypi_name, gh_repo)` tuples
  the sentry watches.
- `.github/workflows/version_sentry.yml` — runs daily 06:00 UTC plus
  manual `workflow_dispatch`. Uploads JSON report as artifact.

#### Run locally

    python scripts/version_sentry.py --config config/sentry-targets.json --json-out sentry-report.json

Exit code 0 = no drift. Exit code 1 = drift detected (one or more
targets out of sync). Optional `--create-issue` opens a GitHub Issue
on this repo when drift is found (CI uses this; local runs default to
report-only).

## Roadmap (R89-04+)

- Portfolio dashboard — single-page HTML on GitHub Pages with per-package
  version, PyPI download count (last 30d via pypistats), GitHub
  star/fork count, last-commit timestamp, CI status badge. Daily
  auto-refresh, no JavaScript.
- Marketplace presence tracker — Anthropic plugin directory + Glama.ai
  install/star snapshot, README badge update.

## License

MIT — see `LICENSE`.
