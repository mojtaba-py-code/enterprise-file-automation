# Contributing

Thanks for taking a look. This is how the project is developed locally and what
CI expects before a change lands.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Before you push

These are exactly the steps CI runs, so run them locally first:

```bash
ruff check src tests
mypy src                          # strict
pytest
```

CI runs the same on Python 3.11 and 3.12.

## Conventions

- **Configuration drives behaviour.** New capabilities are described in the YAML
  config and implemented as a pipeline stage — not hard-coded into the runner.
- **Never mutate the input.** The pipeline reads from the inbox and writes
  derived files elsewhere; the original file is left untouched. Any change that
  breaks that invariant needs an explicit discussion in the PR.
- **Idempotent stages.** Running the same pipeline twice over the same input
  must not produce duplicated or corrupted output.
- **Cross-platform.** Use `pathlib`, not string paths, and no POSIX-only
  permission assumptions — CI runs the suite on Python 3.11 and 3.12 and the
  tool is expected to work on Windows.
- **Types.** `src/file_automation` is strict-typed; `mypy` must stay clean.
- **Tests.** Add tests with the change; file operations run against `tmp_path`
  fixtures, never a real inbox.
- **Commits.** Short imperative subject, a body explaining the *why*.

## Reporting a security problem

Do not open a public issue — see [SECURITY.md](SECURITY.md).
