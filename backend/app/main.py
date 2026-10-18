import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from . import ai, notify, reports, service
from .config import settings
from .db import Base, engine, get_db, utcnow
from .models import Alert, LogEntry, Metric, Node, Pod, Report

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("lensguard")
STATIC = Path(__file__).parent / "static"


def init_db():
    for _ in range(30):  # wait for MySQL to accept connections
        try:
            Base.metadata.create_all(engine)
            return
        except OperationalError:
            time.sleep(2)
    raise RuntimeError("Database unavailable")


async def collect_loop():
    while True:
        await asyncio.to_thread(service.run_cycle)
        await asyncio.sleep(settings.collect_interval)


@asynccontextmanager
async def lifespan(_app):
    await asyncio.to_thread(init_db)
    task = asyncio.create_task(collect_loop()) if settings.collector_enabled else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="LensGuard", description="AI-powered Docker & Kubernetes debugging assistant", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def iso(d):
    return d.isoformat() + "Z" if d else None


def alert_dict(a: Alert):
    return {"id": a.id, "rule": a.rule, "severity": a.severity, "resource": a.resource, "title": a.title,
            "message": a.message, "hint": a.hint, "context": a.context, "status": a.status, "count": a.count,
            "first_seen": iso(a.first_seen), "last_seen": iso(a.last_seen), "resolved_at": iso(a.resolved_at),
            "ai_explanation": a.ai_explanation}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "collector_enabled": settings.collector_enabled,
            "last_collection": iso(service.state["last_run"]), "collector_error": service.state["error"],
            "metrics_available": service.state["metrics_available"], "ai_enabled": ai.available(),
            "notifications_enabled": notify.enabled()}


@app.get("/api/overview")
def overview(db=Depends(get_db)):
    status = dict(db.execute(select(Pod.status, func.count()).group_by(Pod.status)).all())
    open_alerts = dict(db.execute(select(Alert.severity, func.count()).where(Alert.status == "open")
                                  .group_by(Alert.severity)).all())
    return {"pod_status": status, "nodes_total": db.scalar(select(func.count()).select_from(Node)),
            "nodes_ready": db.scalar(select(func.count()).select_from(Node).where(Node.ready.is_(True))),
            "open_alerts": open_alerts}


@app.get("/api/pods")
def pods(db=Depends(get_db)):
    rows = db.scalars(select(Pod).order_by(Pod.namespace, Pod.name))
    return [{"namespace": p.namespace, "name": p.name, "node": p.node, "phase": p.phase, "status": p.status,
             "restarts": p.restarts, "age_s": p.age_s} for p in rows]


@app.get("/api/nodes")
def nodes(db=Depends(get_db)):
    return [{"name": n.name, "ready": n.ready, "cpu_m": n.cpu_m, "cpu_alloc_m": n.cpu_alloc_m,
             "mem_mi": n.mem_mi, "mem_alloc_mi": n.mem_alloc_mi} for n in db.scalars(select(Node).order_by(Node.name))]


@app.get("/api/metrics")
def metrics(minutes: int = 60, db=Depends(get_db)):
    cutoff = utcnow() - timedelta(minutes=min(max(minutes, 1), 1440))
    rows = db.scalars(select(Metric).where(Metric.ts >= cutoff).order_by(Metric.ts))
    return [{"ts": iso(m.ts), "cpu_m": m.cpu_m, "mem_mi": m.mem_mi, "cpu_pct": m.cpu_pct, "mem_pct": m.mem_pct}
            for m in rows]


@app.get("/api/alerts")
def list_alerts(status: str | None = None, db=Depends(get_db)):
    q = select(Alert).order_by(Alert.status.desc(), Alert.last_seen.desc()).limit(200)
    if status in ("open", "resolved"):
        q = q.where(Alert.status == status)
    return [alert_dict(a) for a in db.scalars(q)]


@app.post("/api/alerts/{alert_id}/explain")
def explain_alert(alert_id: int, db=Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    if not ai.available():
        raise HTTPException(403, "AI explanations are off. Set OPENAI_ENABLED=true and OPENAI_API_KEY to opt in.")
    try:
        a.ai_explanation = ai.explain(a)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"AI request failed: {exc}") from exc
    db.commit()
    return {"id": a.id, "ai_explanation": a.ai_explanation}


@app.get("/api/logs")
def logs(resource: str | None = None, limit: int = 50, db=Depends(get_db)):
    q = select(LogEntry).order_by(LogEntry.id.desc()).limit(min(limit, 200))
    if resource:
        q = q.where(LogEntry.resource == resource)
    return [{"ts": iso(x.ts), "resource": x.resource, "kind": x.kind, "message": x.message} for x in db.scalars(q)]


@app.get("/api/reports")
def list_reports(db=Depends(get_db)):
    rows = db.scalars(select(Report).order_by(Report.id.desc()).limit(50))
    return [{"id": r.id, "tool": r.tool, "target": r.target, "created_at": iso(r.created_at), "critical": r.critical,
             "high": r.high, "medium": r.medium, "low": r.low} for r in rows]


@app.get("/api/reports/{report_id}")
def get_report(report_id: int, db=Depends(get_db)):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return {"id": r.id, "tool": r.tool, "target": r.target, "findings": json.loads(r.findings_json)}


@app.post("/api/reports/import")
def import_report(file: UploadFile = File(...), tool: str | None = Form(None), db=Depends(get_db)):
    try:
        parsed = reports.parse(json.loads(file.file.read()), tool)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    r = service.import_report(db, parsed)
    return {"id": r.id, "tool": r.tool, "target": r.target, "critical": r.critical, "high": r.high,
            "medium": r.medium, "low": r.low}


@app.post("/api/collect")
async def collect_now():
    await asyncio.to_thread(service.run_cycle)
    return {"last_collection": iso(service.state["last_run"]), "error": service.state["error"]}
