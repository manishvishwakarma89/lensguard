"""Read-only Kubernetes collector.

Only list/get calls are made (pods, nodes, events, pod logs, metrics.k8s.io).
Nothing here can change cluster state.
"""
import logging
import os
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

log = logging.getLogger("lensguard.collector")

WAITING_PROBLEMS = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
                    "CreateContainerConfigError", "InvalidImageName"}
_loaded = False


def parse_cpu(v) -> float:
    """Kubernetes CPU quantity -> millicores."""
    v = str(v)
    if v.endswith("n"):
        return float(v[:-1]) / 1e6
    if v.endswith("u"):
        return float(v[:-1]) / 1e3
    if v.endswith("m"):
        return float(v[:-1])
    return float(v) * 1000


def parse_mem(v) -> float:
    """Kubernetes memory quantity -> MiB."""
    v = str(v)
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024,
             "K": 1000 / 1048576, "M": 1e6 / 1048576, "G": 1e9 / 1048576}
    for suffix, factor in units.items():
        if v.endswith(suffix):
            return float(v[: -len(suffix)]) * factor
    return float(v) / 1048576


def _load(settings):
    global _loaded
    if _loaded:
        return
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        config.load_incluster_config()
    else:
        config.load_kube_config(context=settings.kube_context)
    _loaded = True


def _pod_status(p):
    reason, restarts = None, 0
    for c in p.status.container_statuses or []:
        restarts += c.restart_count or 0
        st, last = c.state, c.last_state
        if st and st.waiting and st.waiting.reason and st.waiting.reason != "ContainerCreating":
            reason = st.waiting.reason
        elif st and st.terminated and st.terminated.reason not in (None, "Completed"):
            reason = st.terminated.reason
        elif last and last.terminated and last.terminated.reason == "OOMKilled" and not reason:
            reason = "OOMKilled"
    if p.status.reason == "Evicted":
        reason = "Evicted"
    return reason, restarts


def collect(settings) -> dict:
    _load(settings)
    v1 = client.CoreV1Api()
    ignored = {n.strip() for n in settings.ignored_namespaces.split(",") if n.strip()}
    now = datetime.now(timezone.utc)

    pods, log_targets = [], []
    for p in v1.list_pod_for_all_namespaces().items:
        ns = p.metadata.namespace
        if ns in ignored:
            continue
        reason, restarts = _pod_status(p)
        phase = p.status.phase or "Unknown"
        created = p.metadata.creation_timestamp
        pods.append({
            "namespace": ns, "name": p.metadata.name, "node": p.spec.node_name,
            "phase": phase, "reason": reason, "status": reason or phase,
            "restarts": restarts,
            "age_s": int((now - created).total_seconds()) if created else 0,
        })
        if reason in WAITING_PROBLEMS or reason == "OOMKilled" or phase == "Failed":
            log_targets.append(pods[-1])

    # nodes + metrics server
    node_metrics, metrics_ok = {}, True
    try:
        res = client.CustomObjectsApi().list_cluster_custom_object("metrics.k8s.io", "v1beta1", "nodes")
        for item in res.get("items", []):
            u = item["usage"]
            node_metrics[item["metadata"]["name"]] = (parse_cpu(u["cpu"]), parse_mem(u["memory"]))
    except ApiException:
        metrics_ok = False  # metrics-server not installed

    nodes = []
    for n in v1.list_node().items:
        ready = any(c.type == "Ready" and c.status == "True" for c in n.status.conditions or [])
        cpu, mem = node_metrics.get(n.metadata.name, (None, None))
        nodes.append({
            "name": n.metadata.name, "ready": ready, "cpu_m": cpu, "mem_mi": mem,
            "cpu_alloc_m": parse_cpu(n.status.allocatable["cpu"]),
            "mem_alloc_mi": parse_mem(n.status.allocatable["memory"]),
        })

    # warning events
    events = []
    try:
        evs = v1.list_event_for_all_namespaces(field_selector="type=Warning").items
        evs.sort(key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp, reverse=True)
        for e in evs[:100]:
            o = e.involved_object
            if o.kind == "Pod" and o.namespace not in ignored:
                events.append({"resource": f"pod/{o.namespace}/{o.name}",
                               "reason": e.reason or "", "message": (e.message or "")[:500]})
    except ApiException as exc:
        log.warning("events unavailable: %s", exc.reason)

    # log tails for broken pods only (capped)
    logs = {}
    for p in log_targets[:10]:
        try:
            text = v1.read_namespaced_pod_log(
                p["name"], p["namespace"], tail_lines=settings.log_tail_lines,
                previous=p["reason"] in ("CrashLoopBackOff", "OOMKilled"))
        except ApiException:
            try:
                text = v1.read_namespaced_pod_log(p["name"], p["namespace"], tail_lines=settings.log_tail_lines)
            except ApiException:
                continue
        if text.strip():
            logs[f"pod/{p['namespace']}/{p['name']}"] = text[-4000:]

    return {"pods": pods, "nodes": nodes, "events": events, "logs": logs, "metrics_available": metrics_ok}
