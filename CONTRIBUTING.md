# Contributing

Thanks for taking the time to contribute.

## Setup

```bash
uv sync
cp .env.example .env
```

Python 3.12 is required. Run the checks before you open a pull request:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Pull requests

- Keep a PR to one change. Split refactors from behavior changes.
- Add or update tests for any change in behavior. The suite runs without network access; use the fakes in `tests/fakes.py`.
- If you change a route, a response shape, or an error code, update [`docs/api-contract.md`](docs/api-contract.md) in the same PR.
- Add a line to [`CHANGELOG.md`](CHANGELOG.md) under a new version heading when the change is user-visible.
- Use the commit style already in the history: `feat:`, `fix:`, `chore:`, `docs:`, `test:`.

## Code style

- Ruff decides formatting and lint (line length 100, rules `E`, `F`, `I`, `B`, `UP`).
- Business rules belong in `app/domain/` as pure functions. Keep I/O in `app/services/` and `app/store/`.
- Do not add a dependency without a reason in the PR description. Update `uv.lock` with `uv lock`.

## Reporting bugs

Open an issue with the steps to reproduce, the expected result, and the actual result. Do not include secrets, tokens, or personal data in logs or screenshots.

Security issues are handled differently; see [SECURITY.md](SECURITY.md).
