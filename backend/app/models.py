from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime, utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="member")  # admin | member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    environment: Mapped[str] = mapped_column(String(20), default="prod")  # prod | dev | staging
    repo_url: Mapped[str] = mapped_column(String(500), default="")
    monitoring_tools: Mapped[str] = mapped_column(Text, default="")  # ex : "Uptime Kuma, CrowdSec"
    notes: Mapped[str] = mapped_column(Text, default="")

    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    check_interval_min: Mapped[int] = mapped_column(Integer, default=5)
    expected_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # état courant (mis à jour par le worker)
    status: Mapped[str] = mapped_column(String(20), default="unknown")  # up | down | unknown
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    ssl_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cert_fingerprint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    missing_headers: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    servers: Mapped[list["Server"]] = relationship(cascade="all, delete-orphan", back_populates="project")
    technologies: Mapped[list["Technology"]] = relationship(
        cascade="all, delete-orphan", back_populates="project"
    )


class Server(Base):
    __tablename__ = "servers"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(120), default="")  # OVH, Hetzner, AWS…
    hostname: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    os: Mapped[str] = mapped_column(String(120), default="")
    location: Mapped[str] = mapped_column(String(120), default="")
    specs: Mapped[str] = mapped_column(String(255), default="")  # "2 vCPU / 4 Go / 80 Go SSD"
    access_info: Mapped[str] = mapped_column(Text, default="")  # SSH, panel… (JAMAIS de mot de passe)
    notes: Mapped[str] = mapped_column(Text, default="")
    project: Mapped[Project] = relationship(back_populates="servers")


class Technology(Base):
    __tablename__ = "technologies"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))  # nginx, wordpress, php…
    version: Mapped[str] = mapped_column(String(60), default="")
    category: Mapped[str] = mapped_column(String(60), default="")  # backend, frontend, db, os…
    watch_cve: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    project: Mapped[Project] = relationship(back_populates="technologies")


class CheckResult(Base):
    __tablename__ = "check_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str] = mapped_column(String(500), default="")
    ssl_days_left: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Vulnerability(Base):
    __tablename__ = "vulnerabilities"
    __table_args__ = (UniqueConstraint("technology_id", "cve_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    technology_id: Mapped[int] = mapped_column(ForeignKey("technologies.id", ondelete="CASCADE"))
    cve_id: Mapped[str] = mapped_column(String(30))
    cvss: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    exploited: Mapped[bool] = mapped_column(Boolean, default=False)  # dans le catalogue CISA KEV
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    found_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    technology: Mapped[Technology] = relationship()


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(30))  # down | recovered | ssl | attack | vuln | tax | mail
    severity: Mapped[str] = mapped_column(String(10), default="warning")  # info | warning | critical
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text, default="")
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class AlertChannel(Base):
    __tablename__ = "alert_channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(20))  # email | slack | discord | telegram | webhook
    config_enc: Mapped[str] = mapped_column(Text)  # JSON chiffré
    min_severity: Mapped[str] = mapped_column(String(10), default="warning")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Integration(Base):
    """Clés/identifiants des services externes, chiffrés."""

    __tablename__ = "integrations"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_enc: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class MailMessage(Base):
    __tablename__ = "mail_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(400), unique=True)
    conversation_id: Mapped[str] = mapped_column(String(400), default="", index=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    sender_name: Mapped[str] = mapped_column(String(255), default="")
    sender_email: Mapped[str] = mapped_column(String(255), default="")
    preview: Mapped[str] = mapped_column(Text, default="")
    web_link: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_tag: Mapped[str] = mapped_column(String(20), default="info")  # a_repondre | repondu | info
    manual_tag: Mapped[str | None] = mapped_column(String(20), nullable=True)  # a_repondre|urgent|fait|ignore


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_date: Mapped[date] = mapped_column(Date)
    employee: Mapped[str] = mapped_column(String(120), default="")
    reason: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(60), default="")
    project: Mapped[str] = mapped_column(String(120), default="")
    payment_method: Mapped[str] = mapped_column(String(60), default="")
    amount_ttc: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    vat_rate: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False), default=20)
    amount_ht: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    amount_vat: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    notes: Mapped[str] = mapped_column(Text, default="")
    pdf_path: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TaxDeadline(Base):
    __tablename__ = "tax_deadlines"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40), default="autre")  # tva | is | cfe | urssaf | …
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float | None] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="todo")  # todo | paid
    recurrence: Mapped[str] = mapped_column(String(10), default="none")  # none|monthly|quarterly|yearly
    reminder_days: Mapped[str] = mapped_column(String(40), default="30,7,1")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    user_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default="")
