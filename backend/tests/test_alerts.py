from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import alerts
from app.db import Base


def f(fp="X:pod/a"):
    return {"fingerprint": fp, "rule": "X", "severity": "critical", "resource": "pod/a",
            "title": "t", "message": "m", "hint": "h", "context": None}


def test_detect_dedupe_resolve_reopen():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    sent = []
    notifier = sent.append

    assert [k for k, _ in alerts.reconcile(db, [f()], "cluster", notifier)] == ["opened"]
    assert alerts.reconcile(db, [f()], "cluster", notifier) == []          # deduplicated
    assert [k for k, _ in alerts.reconcile(db, [], "cluster", notifier)] == ["resolved"]
    assert [k for k, _ in alerts.reconcile(db, [f()], "cluster", notifier)] == ["reopened"]
    assert len(sent) == 3                                                   # no notification on the duplicate
