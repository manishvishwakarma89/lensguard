"""Parsers for imported security reports: Trivy JSON, Docker Scout SARIF, SonarQube issues JSON."""

SEV = ("critical", "high", "medium", "low")


def _norm(s: str) -> str:
    s = (s or "").lower()
    return {"blocker": "critical", "major": "high", "minor": "medium", "info": "low",
            "moderate": "medium", "unknown": "low", "negligible": "low"}.get(s, s if s in SEV else "low")


def parse_trivy(d):
    target = d.get("ArtifactName") or "unknown"
    out = []
    for r in d.get("Results") or []:
        for v in r.get("Vulnerabilities") or []:
            out.append({"id": v.get("VulnerabilityID", ""), "package": v.get("PkgName", ""),
                        "severity": _norm(v.get("Severity")), "installed": v.get("InstalledVersion", ""),
                        "fixed": v.get("FixedVersion", ""), "title": v.get("Title") or v.get("VulnerabilityID", "")})
    return {"tool": "trivy", "target": target, "findings": out}


def parse_scout(d):
    out, target = [], "unknown"
    for run in d.get("runs") or []:
        rules = {r["id"]: r for r in run.get("tool", {}).get("driver", {}).get("rules", []) if "id" in r}
        for art in run.get("artifacts") or []:
            target = art.get("location", {}).get("uri", target)
        for res in run.get("results") or []:
            rid = res.get("ruleId", "")
            score = rules.get(rid, {}).get("properties", {}).get("security-severity")
            if score is not None:
                s = float(score)
                sev = "critical" if s >= 9 else "high" if s >= 7 else "medium" if s >= 4 else "low"
            else:
                sev = {"error": "high", "warning": "medium"}.get(res.get("level"), "low")
            out.append({"id": rid, "package": "", "severity": sev, "installed": "", "fixed": "",
                        "title": (res.get("message", {}).get("text") or rid)[:200]})
    return {"tool": "docker-scout", "target": target, "findings": out}


def parse_sonar(d):
    out = []
    target = "sonarqube"
    for i in d.get("issues") or []:
        target = i.get("project") or target
        out.append({"id": i.get("rule", ""), "package": i.get("component", ""), "severity": _norm(i.get("severity")),
                    "installed": "", "fixed": "", "title": (i.get("message") or "")[:200]})
    return {"tool": "sonarqube", "target": target, "findings": out}


def parse(data, tool=None):
    """Auto-detect format unless `tool` is given."""
    if not isinstance(data, dict):
        raise ValueError("Report must be a JSON object")
    t = (tool or "").lower().replace("_", "-")
    if t == "trivy" or "Results" in data or "ArtifactName" in data:
        return parse_trivy(data)
    if t in ("docker-scout", "scout") or "runs" in data:
        return parse_scout(data)
    if t in ("sonarqube", "sonar") or "issues" in data:
        return parse_sonar(data)
    raise ValueError("Unrecognised report format (expected Trivy JSON, Docker Scout SARIF or SonarQube issues JSON)")


def counts(findings):
    c = {s: 0 for s in SEV}
    for f in findings:
        c[f["severity"]] += 1
    return c
