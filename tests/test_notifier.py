"""Tests for report rendering and the e-mail notifier (no network)."""

from __future__ import annotations

import smtplib
import ssl
from pathlib import Path
from typing import Any

import pytest

from file_automation.config import EmailConfig
from file_automation.models import ProcessResult
from file_automation.notifier import EmailNotifier, render_report
from file_automation.pipeline import RunReport


def _report() -> RunReport:
    report = RunReport()
    report.add(
        ProcessResult(
            source_path=Path("in/a.txt"),
            status="success",
            original_hash="h1",
            category="documents",
            output_path=Path("out/a.zip"),
        )
    )
    report.add(
        ProcessResult(
            source_path=Path("in/b.txt"),
            status="failed",
            original_hash="h2",
            error="boom",
        )
    )
    return report


def test_render_contains_counts() -> None:
    text = render_report(_report())
    assert "Processed : 2" in text
    assert "Succeeded : 1" in text
    assert "Failed    : 1" in text
    assert "a.zip" in text
    assert "boom" in text


def test_notifier_disabled_does_not_send() -> None:
    notifier = EmailNotifier(EmailConfig(enabled=False))
    assert notifier.notify(_report()) is False


def test_build_message_headers() -> None:
    cfg = EmailConfig(
        enabled=True,
        smtp_host="smtp.example.com",
        sender="from@example.com",
        recipients=("to@example.com",),
        subject_prefix="[FA]",
    )
    msg = EmailNotifier(cfg).build_message(_report())
    assert msg["From"] == "from@example.com"
    assert msg["To"] == "to@example.com"
    assert msg["Subject"].startswith("[FA]")


def test_starttls_verifies_the_server_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SMTP password may only travel over a verified connection."""
    captured: dict[str, Any] = {}

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int = 0) -> None:
            captured["host"] = host

        def __enter__(self) -> _FakeSMTP:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def starttls(self, *, context: ssl.SSLContext | None = None) -> None:
            captured["context"] = context

        def login(self, username: str, password: str) -> None:
            captured["login"] = username

        def send_message(self, message: object) -> None:
            captured["sent"] = True

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    cfg = EmailConfig(
        enabled=True,
        smtp_host="smtp.example.com",
        sender="from@example.com",
        recipients=("to@example.com",),
        use_tls=True,
    )

    assert EmailNotifier(cfg).notify(_report()) is True
    assert captured["sent"] is True

    context = captured["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED


def test_only_on_activity_suppresses_empty() -> None:
    cfg = EmailConfig(
        enabled=True,
        smtp_host="smtp.example.com",
        sender="from@example.com",
        recipients=("to@example.com",),
        only_on_activity=True,
    )
    assert EmailNotifier(cfg).notify(RunReport()) is False
