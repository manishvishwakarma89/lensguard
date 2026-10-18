"""Optional AI explanations. Off by default; only runs when OPENAI_ENABLED=true and a key is set.

Only the alert text, hint and a redacted log/event excerpt are sent, and only when the user clicks
"Explain" on a specific alert. Nothing is sent automatically.
"""
import re

import httpx

from .config import settings

_SECRET = re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)\b(\s*[=:]\s*)\S+")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")


def redact(text: str) -> str:
    return _BEARER.sub("Bearer [REDACTED]", _SECRET.sub(r"\1\2[REDACTED]", text or ""))


def available() -> bool:
    return settings.openai_enabled and bool(settings.openai_api_key)


def explain(alert) -> str:
    if not available():
        raise RuntimeError("AI explanations are disabled. Set OPENAI_ENABLED=true and OPENAI_API_KEY.")
    prompt = (f"Alert: {alert.title}\nResource: {alert.resource}\nDetails: {alert.message}\n"
              f"Known hint: {alert.hint}\n\nEvidence:\n{redact(alert.context or 'none')[:3000]}")
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={"model": settings.openai_model, "temperature": 0.2, "max_tokens": 450, "messages": [
            {"role": "system", "content": "You are a Kubernetes and Docker debugging assistant. Explain the likely "
             "root cause in plain language, then give 2-4 concrete manual steps with kubectl/docker commands. "
             "Only claim what the evidence supports. Be concise."},
            {"role": "user", "content": prompt}]},
        timeout=40)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
