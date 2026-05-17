# Contributing

Thanks for contributing to Agent-Native Middleware API.

## Development Setup

1. Clone the repository.
2. Create a virtual environment.
3. Install dependencies.
4. Run tests.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Branching

- Default branch: `master`
- Feature branches: `feature/<short-description>`
- Fix branches: `fix/<short-description>`

## Pull Requests

Before opening a PR:

- Keep changes focused to one concern.
- Add or update tests for behavioral changes.
- Run `pytest -q` locally.
- If you add or change routes or response models, refresh the committed spec:
  `python scripts/export_openapi.py`
- Update docs (`README.md`, env examples, or API docs) when behavior/config changes.

PR checklist:

- [ ] Tests pass
- [ ] `python scripts/export_openapi.py --check` passes (or run `export_openapi.py` to refresh `docs/openapi.json`)
- [ ] Backward compatibility considered
- [ ] New env vars documented
- [ ] Security impact reviewed

## Commit Style

Preferred format:

- `feat: ...`
- `fix: ...`
- `docs: ...`
- `chore: ...`

## Reporting Bugs

Use GitHub Issues and include:

- expected behavior
- actual behavior
- steps to reproduce
- request/response payloads (redacted)
- runtime info (Python version, environment, deployment target)

## Security Issues

Do not open public issues for sensitive vulnerabilities.  
Follow `SECURITY.md` for responsible disclosure.
