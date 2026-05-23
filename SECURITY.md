# Security Policy

## Supported versions

The latest `main` branch is the actively maintained line. Tagged releases (when published) are best-effort.

## Reporting a vulnerability

If you believe you've found a security vulnerability in `wrg-portfolio`:

1. **Do not** open a public GitHub issue.
2. Use GitHub's [Private Vulnerability Reporting](https://github.com/WRG-11/wrg-portfolio/security/advisories/new) for this repo.
3. Include in your report:
   - Description of the vulnerability
   - Steps to reproduce
   - Impact assessment (what an attacker could do)
   - Suggested mitigation (if known)

## Response timeline

- **Acknowledgement**: within 7 days
- **Initial assessment**: within 14 days
- **Patch / disclosure**: target within 30 days for high-severity issues

## Scope

In scope:
- `scripts/version_sentry.py` and `scripts/dashboard.py`
- The GitHub Actions workflows under `.github/workflows/`
- The rendered dashboard at `docs/index.html`

Out of scope (report to upstream instead):
- Vulnerabilities in PyPI packages this repo monitors (report to those packages directly)
- GitHub Actions runner / GitHub platform issues (report to GitHub)

## Coordinated disclosure

This project follows coordinated disclosure. Please give us reasonable time to investigate and patch before public disclosure.
