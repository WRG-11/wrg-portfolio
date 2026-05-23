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

### dashboard

Single-page HTML snapshot of every WRG-11 package: PyPI version, GitHub
Release tag, drift status, monthly PyPI downloads, GitHub stars + forks,
last-commit relative date. No JavaScript, no fonts, no tracking pixels --
the whole page is one self-contained `index.html`. Served by GitHub Pages
from the `/docs` folder on `main`; live at
**https://wrg-11.github.io/wrg-portfolio/** (after Pages is enabled in
repo Settings -> Pages -> Build from `main` branch `/docs` folder).

- `scripts/dashboard.py` -- the generator (stdlib only).
- `docs/index.html` -- the rendered page, committed and served.
- `.github/workflows/dashboard.yml` -- runs daily 07:00 UTC and on
  manual `workflow_dispatch`. If the rendered page differs from the
  one on `main`, it commits the new version as
  `github-actions[bot]`. Permissions: `contents: write`.

Manual regeneration:

    python scripts/dashboard.py --config config/sentry-targets.json --out docs/index.html

## Roadmap (R89-04+)

- Marketplace presence tracker -- Anthropic plugin directory + Glama.ai
  install/star snapshot, README badge update.
- Mastodon (infosec.exchange) publisher -- post a one-line announcement
  when a new GitHub Release ships in any WRG-11 package. Operator
  approval per post.

## License

MIT — see `LICENSE`.
