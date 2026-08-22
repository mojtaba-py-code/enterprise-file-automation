"""E-mail reporting of run results.

The message body is built by a pure function (:func:`render_report`) so it can
be unit-tested without any network. Actual delivery uses ``smtplib`` with
STARTTLS against a verified certificate; credentials come from the environment,
never the config file.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from .config import EmailConfig
from .logger import get_logger
from .pipeline import RunReport

_log = get_logger("notifier")


def render_report(report: RunReport) -> str:
    """Render a plain-text summary of a run (also handy for logs)."""
    lines = [
        "File Automation — run report",
        "=" * 32,
        f"Processed : {report.processed}",
        f"Succeeded : {report.succeeded}",
        f"Failed    : {report.failed}",
        f"Skipped   : {report.skipped}",
        "",
    ]
    if report.results:
        lines.append("Details:")
        for r in report.results:
            marker = {"success": "OK  ", "failed": "FAIL", "skipped": "SKIP"}[r.status]
            detail = r.output_path.name if r.output_path else (r.error or "")
            lines.append(f"  [{marker}] {r.source_path.name} -> {detail}")
    return "\n".join(lines)


class EmailNotifier:
    def __init__(self, cfg: EmailConfig) -> None:
        self._cfg = cfg

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    def build_message(self, report: RunReport) -> EmailMessage:
        """Construct the e-mail message (no I/O)."""
        msg = EmailMessage()
        subject = (
            f"{self._cfg.subject_prefix} {report.succeeded} ok, {report.failed} failed"
        )
        msg["Subject"] = subject.strip()
        msg["From"] = self._cfg.sender
        msg["To"] = ", ".join(self._cfg.recipients)
        msg.set_content(render_report(report))
        return msg

    def notify(self, report: RunReport) -> bool:
        """Send the report if enabled and warranted. Returns True if sent."""
        if not self._cfg.enabled:
            return False
        if self._cfg.only_on_activity and not report.had_activity:
            _log.debug("no activity; skipping e-mail report")
            return False

        message = self.build_message(report)
        username = os.environ.get(self._cfg.username_env)
        password = os.environ.get(self._cfg.password_env)
        try:
            with smtplib.SMTP(self._cfg.smtp_host, self._cfg.smtp_port, timeout=30) as server:
                if self._cfg.use_tls:
                    # Without an explicit context smtplib falls back to one that
                    # verifies nothing, so any on-path server could present its
                    # own certificate and collect the password below.
                    server.starttls(context=ssl.create_default_context())
                if username and password:
                    server.login(username, password)
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            # A reporting failure must never crash the automation run.
            _log.error("failed to send e-mail report: %s", exc)
            return False
        _log.info("e-mail report sent to %s", ", ".join(self._cfg.recipients))
        return True
