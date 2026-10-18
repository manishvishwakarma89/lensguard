from app import rules


def pod(name, phase="Running", reason=None, restarts=0, age_s=0):
    return {"namespace": "demo", "name": name, "node": "n1", "phase": phase, "reason": reason,
            "status": reason or phase, "restarts": restarts, "age_s": age_s}


def test_crashloop_is_critical_and_has_context():
    snap = {"pods": [pod("api", reason="CrashLoopBackOff", restarts=4)], "nodes": [],
            "events": [{"resource": "pod/demo/api", "reason": "BackOff", "message": "restarting"}],
            "logs": {"pod/demo/api": "boom"}}
    f = rules.evaluate(snap)
    assert len(f) == 1 and f[0]["severity"] == "critical"
    assert f[0]["fingerprint"] == "CrashLoopBackOff:pod/demo/api"
    assert "boom" in f[0]["context"] and "BackOff" in f[0]["context"]


def test_pending_only_after_threshold():
    assert rules.evaluate({"pods": [pod("a", "Pending", age_s=30)], "nodes": []}) == []
    assert rules.evaluate({"pods": [pod("a", "Pending", age_s=300)], "nodes": []})[0]["rule"] == "PodPending"


def test_high_restarts_and_healthy_pod():
    assert rules.evaluate({"pods": [pod("a", restarts=9)], "nodes": []})[0]["rule"] == "HighRestarts"
    assert rules.evaluate({"pods": [pod("ok")], "nodes": []}) == []


def test_node_rules():
    node = {"name": "n1", "ready": False, "cpu_m": 900, "cpu_alloc_m": 1000, "mem_mi": 100, "mem_alloc_mi": 1000}
    got = {f["rule"] for f in rules.evaluate({"pods": [], "nodes": [node]})}
    assert got == {"NodeNotReady", "HighCPU"}
