"""Alert engine: detect -> deduplicate -> resolve."""
from sqlalchemy import select

from . import notify
from .db import utcnow
from .models import Alert


def reconcile(db, findings, source, notifier=notify.alert_events):
    """Sync the alerts of one `source` with the current findings.

    - new fingerprint            -> open alert, notify
    - known fingerprint again    -> bump count/last_seen, no notification (dedupe)
    - resolved fingerprint again -> reopen, notify
    - open alert not in findings -> resolve, notify
    """
    now = utcnow()
    current = {f["fingerprint"]: f for f in findings}
    existing = {a.fingerprint: a for a in db.scalars(select(Alert).where(Alert.source == source))}
    events = []

    for fp, f in current.items():
        a = existing.get(fp)
        if a is None:
            a = Alert(fingerprint=fp, source=source, rule=f["rule"], severity=f["severity"],
                      resource=f["resource"], title=f["title"], message=f["message"],
                      hint=f.get("hint"), context=f.get("context"), first_seen=now, last_seen=now)
            db.add(a)
            events.append(("opened", a))
        else:
            a.last_seen, a.count = now, a.count + 1
            a.message, a.severity = f["message"], f["severity"]
            if f.get("context"):
                a.context = f["context"]
            if a.status == "resolved":
                a.status, a.resolved_at, a.ai_explanation = "open", None, None
                events.append(("reopened", a))

    for fp, a in existing.items():
        if fp not in current and a.status == "open":
            a.status, a.resolved_at = "resolved", now
            events.append(("resolved", a))

    db.commit()
    if events:
        notifier(events)
    return events
