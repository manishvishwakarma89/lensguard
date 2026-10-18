"""Optional Slack + email notifications. Failures never break the pipeline."""
import logging
import smtplib
from email.message import EmailMessage

import httpx

from .config import settings

log = logging.getLogger("lensguard.notify")
ORDER = {"info": 0, "warning": 1, "critical": 2}
ICON = {"opened": "🔴", "reopened": "🟠", "resolved": "✅"}


def enabled() -> bool:
    return bool(settings.slack_webhook_url or (settings.smtp_host and settings.email_to))


def wants(severity: str) -> bool:
    return ORDER.get(severity, 0) >= ORDER.get(settings.notify_min_severity, 1)


def send(subject: str, body: str) -> None:
    if settings.slack_webhook_url:
        try:
            httpx.post(settings.slack_webhook_url, json={"text": f"*{subject}*\n{body}"}, timeout=5)
        except Exception as exc:  # noqa: BLE001
            log.warning("slack failed: %s", exc)
    if settings.smtp_host and settings.email_to:
        try:
            msg = EmailMessage()
            msg["Subject"], msg["From"] = f"[LensGuard] {subject}", settings.email_from or settings.smtp_user
            msg["To"] = settings.email_to
            msg.set_content(body)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
                s.starttls()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        except Exception as exc:  # noqa: BLE001
            log.warning("email failed: %s", exc)


def alert_events(events) -> None:
    """events: list of (kind, alert). One message per event, or a single summary if there are many."""
    events = [(k, a) for k, a in events if wants(a.severity)]
    if not events or not enabled():
        return
    if len(events) > 5:
        lines = [f"{ICON[k]} {k}: {a.title} ({a.resource})" for k, a in events[:25]]
        more = f"\n…and {len(events) - 25} more" if len(events) > 25 else ""
        send(f"{len(events)} alert changes", "\n".join(lines) + more)
        return
    for kind, a in events:
        send(f"{ICON[kind]} {kind.capitalize()}: {a.title}",
             f"{a.severity.upper()} · {a.resource}\n{a.message}\n\nNext step: {a.hint or '-'}")
