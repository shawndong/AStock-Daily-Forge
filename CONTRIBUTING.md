# Contributing Guide

## Development setup

```bash
cd src
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -q
```

## Branch & PR recommendations

- Use short feature branches: `feat/*`, `fix/*`, `docs/*`.
- Keep each PR focused on one topic.
- Include before/after behavior for pipeline-impacting changes.

## Coding rules

- Do not hardcode阈值 in business logic; put them in `config/settings.py`.
- Missing data must be written as `N/A`.
- New file IO should go through `storage/reader.py` or `storage/writer.py`.
- Keep daily jobs idempotent where possible.

## Testing

- Add or update tests under `src/tests/` for behavior changes.
- For parser/data-shape changes, include at least one malformed-input test.
- For scheduler changes, verify both trading day and non-trading day paths.

## Data & repository hygiene

- Runtime data directories are generated artifacts and ignored by `.gitignore`.
- Do not commit local virtual envs or logs.

## Documentation

- Update `README.md` for user-visible behavior changes.
- Update `docs/PROJECT_REVIEW.md` when architecture-level decisions change.
