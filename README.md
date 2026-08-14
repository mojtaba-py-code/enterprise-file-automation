# Enterprise File Automation

[![CI](https://github.com/mojtaba-py-code/enterprise-file-automation/actions/workflows/ci.yml/badge.svg)](https://github.com/mojtaba-py-code/enterprise-file-automation/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org)
[![Typed](https://img.shields.io/badge/typed-mypy-2A6DB2.svg)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/badge/style-ruff-D7FF64.svg)](https://docs.astral.sh/ruff/)
[![Security](https://img.shields.io/badge/security-bandit%20%2B%20pip--audit-4B8BBE.svg)](SECURITY.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A professional, **config-driven** file-automation pipeline. Drop files into an
inbox and the system classifies, converts, renames, compresses, encrypts, backs
up and reports on them — on a schedule, idempotently, and without ever touching
your original files.

## Features

| Capability | Module | Notes |
|---|---|---|
| Scheduled batch scanning | `scheduler.py` | Every *N* minutes via `schedule` |
| New-file detection | `watcher.py` + `state.py` | SHA-256 content hashing |
| Classification | `processors/classifier.py` | Extension → category rules |
| Format conversion | `processors/converter.py` | Image↔image, image→PDF (Pillow) |
| Standardized renaming | `processors/renamer.py` | Deterministic, collision-safe |
| Compression | `processors/compressor.py` | ZIP (DEFLATE) |
| Encryption | `processors/encryptor.py` | Fernet; key from env, never on disk |
| Backup | `processors/backup.py` | Per-category snapshot |
| E-mail reports | `notifier.py` | SMTP + STARTTLS, opt-in |
| Logging | `logger.py` | Console + rotating file |
| Config | `config.py` | Validated YAML |

## Architecture

```
scheduler ─► watcher (hash + state) ─► pipeline ─► [ classify → convert →
             rename → compress → encrypt → backup ] ─► output/ + backups/
                                          │
                                          └─► logger + e-mail report
```

The pipeline is a chain of interchangeable **processors** sharing one interface
(`processors/base.py`). Each step reads a `FileContext` and returns it, so
adding a capability is a new subclass plus one line of config. Every file is
processed on an isolated **staging copy**; the inbox is never mutated and a
failure in one file never aborts the run.

### Idempotency & state

`state.json` records the SHA-256 of every processed file. Unchanged files are
skipped, edited files (new hash) are reprocessed, and files that keep failing
are retried up to `max_retries` and then quarantined to `failed/`.

## Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    •    POSIX: source .venv/bin/activate
pip install -e ".[dev]"
```

## Configure

```bash
cp config/config.example.yaml config/config.yaml
cp .env.example .env
file-automation keygen   # put the printed key in .env as FILE_AUTOMATION_ENCRYPTION_KEY
```

Edit `config/config.yaml` to taste. **Secrets stay in `.env`**, never in the
YAML or in git.

## Usage

```bash
file-automation init        # create working directories
file-automation run-once    # one scan/process cycle (great for cron/testing)
file-automation run         # start the scheduler (runs forever)
file-automation keygen      # generate a new encryption key
```

Exit codes: `0` success, `1` some files failed, `2` configuration error.

## Security notes

- Encryption keys and SMTP passwords are read from environment variables only.
- `.env`, `config/config.yaml`, `state.json` and all runtime data are
  git-ignored by default.
- Compression always precedes encryption (encrypted data is incompressible).

## Development

```bash
pytest            # test-suite
ruff check .      # lint
mypy              # strict type-checking
```

## License

MIT — see [LICENSE](LICENSE).
