# Contributing — MERQO Retvia

This is a proprietary commercial product. Contributions are limited to
authorized maintainers.

## Branch strategy

The Arena agent session works on the fixed branch
`arena/aba4099c-merqo-retail-management-system`. Human maintainers should
use the following strategy on the canonical repository:

- `main` — stable, production-ready code
- `develop` — integration branch
- `feature/*` — individual features
- `bugfix/*` — bug fixes
- `release/*` — release preparation
- `hotfix/*` — critical production fixes

> Note: the automated agent is constrained to its session branch and will
> not create or push other branches. Merges to `main`/`develop` are done by
> the maintainer via pull request.

## Commit convention

Use clear, conventional commits:

```
feat: implement product management
fix: resolve stock reconciliation issue
test: add financial calculation tests
build: configure Windows installer
docs: update user guide
chore: initialize project architecture
release: publish version 1.0.0
```

## Quality gates (must pass before merge)

1. `npm run typecheck`
2. `npm run lint`
3. `npm test`
4. `npm run build` (renderer + main + preload)

## Rules

- No placeholders, fake functionality, static dashboard data or dummy
  reports.
- Every feature needs: UI, validation, business logic, DB integration,
  error handling, audit trail (where relevant), automated tests, docs.
- Financial calculations live only in the centralized calculation engine
  (integer minor units). Never use floating point for money.
- Never commit secrets, private keys, or real business data.
