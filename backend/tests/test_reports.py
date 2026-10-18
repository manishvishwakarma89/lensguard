import pytest

from app import ai, reports


def test_trivy():
    p = reports.parse({"ArtifactName": "app:1", "Results": [{"Vulnerabilities": [
        {"VulnerabilityID": "CVE-1", "PkgName": "openssl", "Severity": "CRITICAL",
         "InstalledVersion": "1.0", "FixedVersion": "1.1"}]}]})
    assert p["tool"] == "trivy" and p["target"] == "app:1"
    assert reports.counts(p["findings"])["critical"] == 1


def test_scout_sarif_uses_security_severity():
    p = reports.parse({"runs": [{"tool": {"driver": {"rules": [{"id": "CVE-2", "properties": {"security-severity": "7.5"}}]}},
                                 "results": [{"ruleId": "CVE-2", "message": {"text": "bad"}}]}]})
    assert p["findings"][0]["severity"] == "high"


def test_sonar_and_unknown():
    p = reports.parse({"issues": [{"rule": "r", "severity": "BLOCKER", "message": "m", "component": "c"}]})
    assert p["findings"][0]["severity"] == "critical"
    with pytest.raises(ValueError):
        reports.parse({"foo": 1})


def test_redaction():
    out = ai.redact("password=hunter2 and Authorization: Bearer abc.def")
    assert "hunter2" not in out and "abc.def" not in out
