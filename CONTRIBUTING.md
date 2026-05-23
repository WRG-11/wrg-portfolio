# Contributing to wrg-portfolio

Thanks for your interest. This repo is the self-hosted health monitor for the WRG-11 open-source ecosystem, but the structure is intentionally generic — you can fork it to monitor any GitHub org's PyPI packages.

## Ways to contribute

- **Add a target package** — edit `config/sentry-targets.json` (for the WRG-11 org) or fork + replace for your own org
- **Dashboard improvements** — `scripts/dashboard.py` (stdlib only; no new external deps)
- **Sentry expansions** — `scripts/version_sentry.py` or a new sister sentry script
- **Documentation** — README polish, examples, fork-friendliness guides
- **Bug reports + feature requests** — via [issues](https://github.com/WRG-11/wrg-portfolio/issues) using the templates

## Development setup

```bash
git clone https://github.com/WRG-11/wrg-portfolio.git
cd wrg-portfolio

# Sentry dry run (no GitHub auth required for read-only check)
python scripts/version_sentry.py --config config/sentry-targets.json --json-out /tmp/sentry-report.json

# Dashboard regeneration
python scripts/dashboard.py --config config/sentry-targets.json --out docs/index.html
```

No `pip install` needed — both scripts are stdlib-only. Python 3.11+ recommended.

## PR bar

- **Zero external dependencies** in `scripts/` (stdlib only — `urllib.request`, `json`, `subprocess`, `argparse`, `pathlib`). This is a non-negotiable architectural rule.
- **Update `CHANGELOG.md`** under `[Unreleased]` with a one-line summary.
- **Test locally** — at minimum, run the affected script and confirm no crash.
- **Match existing style** — short functions, type hints, no surprise abstractions.

## Commit messages

Follow conventional-commit-ish format:
- `feat(dashboard): add CodeQL alert count column`
- `fix(sentry): handle PyPI 404 gracefully`
- `docs(readme): clarify fork-and-reuse instructions`
- `chore(deps): bump actions/checkout to v5`

Co-authored / generated-by trailers are discouraged.

## Code of conduct

By participating, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Contributions are accepted under the [MIT License](LICENSE).
