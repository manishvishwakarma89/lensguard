"""Collection cycle: collect -> store -> evaluate rules -> reconcile alerts."""
import json
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from . import alerts, collector, rules
from .config import settings
from .db import SessionLocal, utcnow
from .models import LogEntry, Metric, Node, Pod, Report
from .reports import counts

log = logging.getLogger("lensguard")
state = {"last_run": None, "error": None, "metrics_available": None}


def store(db, snap):
    db.execute(delete(Pod))
    db.execute(delete(Node))
    for p in snap["pods"]:
        db.add(Pod(**{k: p[k] for k in ("namespace", "name", "node", "phase", "status", "restarts", "age_s")}))
    for n in snap["nodes"]:
        db.add(Node(**n))

    measured = [n for n in snap["nodes"] if n["cpu_m"] is not None]
    if measured:
        cpu, mem = sum(n["cpu_m"] for n in measured), sum(n["mem_mi"] for n in measured)
        cpu_a, mem_a = sum(n["cpu_alloc_m"] for n in measured), sum(n["mem_alloc_mi"] for n in measured)
        db.add(Metric(cpu_m=cpu, mem_mi=mem, cpu_pct=cpu / cpu_a * 100 if cpu_a else 0,
                      mem_pct=mem / mem_a * 100 if mem_a else 0))

    entries = [(res, "log", text) for res, text in snap["logs"].items()]
    entries += [(e["resource"], "event", f"{e['reason']}: {e['message']}") for e in snap["events"][:30]]
    for res, kind, msg in entries:
        last = db.scalar(select(LogEntry).where(LogEntry.resource == res, LogEntry.kind == kind)
                         .order_by(LogEntry.id.desc()).limit(1))
        if not last or last.message != msg:
            db.add(LogEntry(resource=res, kind=kind, message=msg))
    db.commit()


def prune(db):
    now = utcnow()
    db.execute(delete(Metric).where(Metric.ts < now - timedelta(hours=24)))
    db.execute(delete(LogEntry).where(LogEntry.ts < now - timedelta(days=7)))
    db.commit()


def run_cycle():
    try:
        snap = collector.collect(settings)
    except Exception as exc:  # noqa: BLE001 - cluster may be down; keep serving the dashboard
        state["error"] = f"{type(exc).__name__}: {exc}"[:300]
        log.warning("collection failed: %s", state["error"])
        return
    state.update(error=None, last_run=utcnow(), metrics_available=snap["metrics_available"])
    with SessionLocal() as db:
        store(db, snap)
        findings = rules.evaluate(snap, settings.cpu_alert_pct, settings.mem_alert_pct,
                                  settings.restart_threshold, settings.pending_after_seconds)
        alerts.reconcile(db, findings, "cluster")
        prune(db)


def import_report(db, parsed):
    f = parsed["findings"]
    c = counts(f)
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    top = sorted(f, key=lambda x: rank[x["severity"]])[:200]
    rep = Report(tool=parsed["tool"], target=parsed["target"], findings_json=json.dumps(top), **c)
    db.add(rep)
    db.commit()

    source = f"report:{parsed['tool']}:{parsed['target']}"[:255]
    findings = []
    for x in top:
        if x["severity"] not in ("critical", "high") or len(findings) >= 50:
            continue
        fix = (f"Upgrade {x['package']} to {x['fixed']}." if x.get("fixed")
               else "Review the finding and patch or mitigate.")
        findings.append({
            "fingerprint": f"vuln:{parsed['tool']}:{parsed['target']}:{x['id']}:{x['package']}"[:255],
            "rule": "Vulnerability", "severity": "critical" if x["severity"] == "critical" else "warning",
            "resource": parsed["target"], "title": f"{x['id']} in {x['package'] or parsed['target']}"[:255],
            "message": f"{x['severity'].upper()} {x['title']} (installed {x['installed'] or '?'}, "
                       f"fixed {x['fixed'] or 'n/a'})",
            "hint": fix, "context": None})
    alerts.reconcile(db, findings, source)
    return rep
