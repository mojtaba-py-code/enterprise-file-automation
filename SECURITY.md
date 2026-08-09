# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

Security fixes are applied to `main` and released from there.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub's
[Report a vulnerability](https://github.com/mojtaba-py-code/enterprise-file-automation/security/advisories/new)
form, or by email to **mojtaba.python@gmail.com**.

Include what you can:

- the affected version, tag or commit,
- what the issue is and what an attacker gains from it,
- steps or a minimal proof of concept that reproduces it.

## What to expect

- Acknowledgement within **72 hours**.
- An initial assessment within **7 days**.
- A fix and a published advisory once a patch is ready.
- Credit in the advisory, if you want it.

## Scope

The pipeline processes files that arrive from outside — filenames and contents
are untrusted input. In scope:

- path traversal or symlink escape via a crafted filename, so that a stage reads
  or writes outside the configured directories,
- a stage that damages or overwrites an original input file,
- a decompression or conversion bomb that exhausts disk or memory,
- an encryption key or passphrase reaching a log line, a report, or a
  world-readable file,
- code execution through the YAML configuration or through a converted file
  format.

Out of scope:

- Vulnerabilities in third-party dependencies (Pillow, cryptography, PyYAML …) —
  report those upstream; if this project's use of one is what makes it
  exploitable, that *is* in scope.
- Findings that require an attacker to already control the host or the process.

## Notes for operators

- Point the inbox at a directory you control, and do not run the pipeline as a
  privileged user.
- Encryption passphrases come from the environment, never from the config file
  or the command line.
- Configuration is loaded as plain YAML data. Do not extend it with a loader
  that can construct arbitrary Python objects.
