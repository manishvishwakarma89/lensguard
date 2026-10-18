"""Rule evaluation. Pure functions: snapshot in, findings out (easy to unit test)."""

HINTS = {
    "CrashLoopBackOff": ("critical", "Container keeps crashing",
        "Read the log tail and last exit code: `kubectl logs <pod> --previous` and `kubectl describe pod <pod>`. "
        "Usual causes: wrong command/args, missing ConfigMap or Secret, failing dependency, bad probe."),
    "ImagePullBackOff": ("critical", "Image cannot be pulled",
        "Check the image name and tag, registry access and imagePullSecrets. For kind/minikube, load local images "
        "with `kind load docker-image` or `minikube image load`."),
    "ErrImagePull": ("critical", "Image pull failed",
        "Check the image name and tag, registry access and imagePullSecrets."),
    "InvalidImageName": ("critical", "Invalid image name", "Fix the image reference in the manifest."),
    "CreateContainerConfigError": ("critical", "Container config error",
        "A referenced ConfigMap/Secret key is probably missing. Run `kubectl describe pod <pod>`."),
    "OOMKilled": ("critical", "Container ran out of memory",
        "Raise resources.limits.memory or fix the memory leak. Compare usage with `kubectl top pod`."),
    "Evicted": ("warning", "Pod was evicted",
        "The node was under resource pressure. Check node conditions and set sensible requests/limits."),
}


def _finding(rule, severity, resource, title, message, hint, context=None):
    return {"fingerprint": f"{rule}:{resource}", "rule": rule, "severity": severity,
            "resource": resource, "title": title, "message": message, "hint": hint, "context": context}


def _context(snapshot, resource):
    parts = []
    for e in snapshot.get("events", []):
        if e["resource"] == resource:
            parts.append(f"event {e['reason']}: {e['message']}")
    log_text = snapshot.get("logs", {}).get(resource)
    if log_text:
        parts.append("log tail:\n" + log_text)
    return "\n".join(parts[:6]) or None


def evaluate(snapshot, cpu_pct=85, mem_pct=85, restart_threshold=5, pending_after=120):
    out = []
    for p in snapshot.get("pods", []):
        res = f"pod/{p['namespace']}/{p['name']}"
        reason = p.get("reason")
        if reason in HINTS:
            sev, title, hint = HINTS[reason]
            out.append(_finding(reason, sev, res, f"{title}: {p['name']}",
                                f"{res} is {reason} on {p.get('node') or 'no node'} "
                                f"({p['restarts']} restarts).", hint, _context(snapshot, res)))
        elif p["phase"] == "Pending" and p.get("age_s", 0) >= pending_after:
            out.append(_finding("PodPending", "warning", res, f"Pod stuck Pending: {p['name']}",
                                f"{res} has been Pending for {p['age_s']}s.",
                                "Run `kubectl describe pod <pod>` and read the events: insufficient CPU/memory, "
                                "taints, node selectors or an unbound PersistentVolumeClaim.",
                                _context(snapshot, res)))
        elif p["phase"] == "Failed":
            out.append(_finding("PodFailed", "warning", res, f"Pod failed: {p['name']}",
                                f"{res} is in phase Failed.", "Inspect `kubectl describe pod` and the logs.",
                                _context(snapshot, res)))
        if p["restarts"] >= restart_threshold and reason != "CrashLoopBackOff":
            out.append(_finding("HighRestarts", "warning", res, f"Frequent restarts: {p['name']}",
                                f"{res} restarted {p['restarts']} times.",
                                "Check liveness probes, resource limits and application logs.",
                                _context(snapshot, res)))

    for n in snapshot.get("nodes", []):
        res = f"node/{n['name']}"
        if not n["ready"]:
            out.append(_finding("NodeNotReady", "critical", res, f"Node not ready: {n['name']}",
                                f"{res} reports Ready=False.",
                                "Run `kubectl describe node` and check kubelet, disk and network. "
                                "For kind/minikube, restart the node container or cluster."))
        if n.get("cpu_m") is not None and n["cpu_alloc_m"]:
            pct = n["cpu_m"] / n["cpu_alloc_m"] * 100
            if pct >= cpu_pct:
                out.append(_finding("HighCPU", "warning", res, f"High CPU on {n['name']}",
                                    f"CPU at {pct:.0f}% of allocatable.",
                                    "Find heavy pods with `kubectl top pod -A --sort-by=cpu`."))
        if n.get("mem_mi") is not None and n["mem_alloc_mi"]:
            pct = n["mem_mi"] / n["mem_alloc_mi"] * 100
            if pct >= mem_pct:
                out.append(_finding("HighMemory", "warning", res, f"High memory on {n['name']}",
                                    f"Memory at {pct:.0f}% of allocatable.",
                                    "Find heavy pods with `kubectl top pod -A --sort-by=memory`."))
    return out
