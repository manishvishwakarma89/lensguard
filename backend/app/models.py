from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, utcnow


class Pod(Base):
    """Latest pod snapshot (replaced every collection cycle)."""
    __tablename__ = "pods"
    id: Mapped[int] = mapped_column(primary_key=True)
    namespace: Mapped[str] = mapped_column(String(253))
    name: Mapped[str] = mapped_column(String(253))
    node: Mapped[str | None] = mapped_column(String(253), nullable=True)
    phase: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(64))
    restarts: Mapped[int] = mapped_column(Integer, default=0)
    age_s: Mapped[int] = mapped_column(Integer, default=0)


class Node(Base):
    """Latest node snapshot (replaced every collection cycle)."""
    __tablename__ = "nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(253))
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    cpu_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_alloc_m: Mapped[float] = mapped_column(Float, default=0)
    mem_mi: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_alloc_mi: Mapped[float] = mapped_column(Float, default=0)


class Metric(Base):
    """Cluster-wide CPU / memory time series."""
    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    cpu_m: Mapped[float] = mapped_column(Float)
    mem_mi: Mapped[float] = mapped_column(Float)
    cpu_pct: Mapped[float] = mapped_column(Float)
    mem_pct: Mapped[float] = mapped_column(Float)


class LogEntry(Base):
    """Pod log tails and warning events (stored only when they change)."""
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    resource: Mapped[str] = mapped_column(String(400))
    kind: Mapped[str] = mapped_column(String(16))  # log | event
    message: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("ix_logs_resource_kind", "resource", "kind"),)


class Report(Base):
    """Imported security report summary (Trivy, Docker Scout, SonarQube)."""
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    tool: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    critical: Mapped[int] = mapped_column(Integer, default=0)
    high: Mapped[int] = mapped_column(Integer, default=0)
    medium: Mapped[int] = mapped_column(Integer, default=0)
    low: Mapped[int] = mapped_column(Integer, default=0)
    findings_json: Mapped[str] = mapped_column(Text)  # capped list of findings


class Alert(Base):
    """Deduplicated alert with open / resolved lifecycle."""
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(255), unique=True)
    source: Mapped[str] = mapped_column(String(255), index=True)
    rule: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    resource: Mapped[str] = mapped_column(String(400))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
