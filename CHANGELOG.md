# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- CI builds the container image, runs its entrypoint and fails if the image
  would run as root. The `Dockerfile` and the README's `docker build` recipe
  shipped without anything ever exercising them.

## [1.1.0] - 2026-08-22

### Added
- Container image: a multi-stage `Dockerfile` that installs from wheels and
  runs the pipeline as an unprivileged uid. The config, the watched
  directories and the encryption key are supplied at run time, never baked in.
- `convert.max_pixels`, an explicit ceiling on the image the converter is
  willing to decode.
- Security policy (`SECURITY.md`) and a contributing guide.
- A weekly CI run, so bandit and pip-audit re-check unchanged pins against a
  fresh advisory database, plus a secret scan across the whole history.

### Changed
- GitHub Actions are pinned to commit SHAs and the workflow token is scoped to
  `contents: read`.
- Dependency floors raised past releases with published CVEs, and setuptools is
  upgraded on the runner before pip-audit inspects the environment.
- Repository links and package metadata point at the kebab-case repository
  name.
- Logs and the watched tree are no longer tracked in git: both are runtime
  output that records the paths a real deployment processed.

### Fixed
- A decompression bomb no longer ends the run. Pillow reports one through
  `DecompressionBombError`/`DecompressionBombWarning`, neither of which is an
  `OSError`, so it escaped the converter's handler and the pipeline's; both are
  now reported as a converter error against that one file.
- Anything else a processor raises is recorded as a failure of that file, with
  a traceback, instead of aborting the batch.
- A file that keeps failing is copied to `failed/` once, on its last permitted
  attempt, rather than once per retry — `max_retries` copies of the same input
  no longer pile up.

### Security
- STARTTLS is negotiated with a verifying SSL context. Without one, `smtplib`
  falls back to a context that checks neither hostname nor certificate, so
  anything on the path could have collected the SMTP password.
- Symlinks in the inbox are logged and skipped instead of followed, so a link
  planted there can no longer have its target copied to `output/` and
  `backups/`.
- Key, certificate and credential filenames are git-ignored.

## [1.0.0] - 2026-07-22

### Added
- Initial release: a config-driven pipeline that watches an inbox and
  classifies, converts, renames, compresses, encrypts and backs up what lands
  there, on a schedule.
- SHA-256 content state, so unchanged files are skipped, edited files are
  reprocessed and files that keep failing are retried a bounded number of
  times.
- Interchangeable processors behind one interface; every file is handled on a
  staging copy, leaving the inbox untouched.
- Optional e-mail reporting, console and rotating-file logging, and a CLI with
  `run`, `run-once`, `init` and `keygen`.

[Unreleased]: https://github.com/mojtaba-py-code/enterprise-file-automation/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/mojtaba-py-code/enterprise-file-automation/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/mojtaba-py-code/enterprise-file-automation/releases/tag/v1.0.0
