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
    role: Mapped[str] = mapped_column(String(20), default="member")  # admin | manager | member
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
    public_status: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # visible sur la page de statut publique
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


# ======================= CRM =======================
class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="prospect")  # prospect|client|supplier|partner
    siret: Mapped[str] = mapped_column(String(20), default="")
    vat_number: Mapped[str] = mapped_column(String(30), default="")
    website: Mapped[str] = mapped_column(String(300), default="")
    sector: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    postal_code: Mapped[str] = mapped_column(String(12), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    country: Mapped[str] = mapped_column(String(60), default="France")
    tags: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    first_name: Mapped[str] = mapped_column(String(120), default="")
    last_name: Mapped[str] = mapped_column(String(120), default="")
    job_title: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    phone: Mapped[str] = mapped_column(String(40), default="")
    tags: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    stage: Mapped[str] = mapped_column(
        String(20), default="prospect"
    )  # prospect|contact|quote|negotiation|won|lost
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0)
    probability: Mapped[int] = mapped_column(Integer, default=20)
    expected_close: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_email: Mapped[str] = mapped_column(String(255), default="")
    next_action: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="note")  # note|call|meeting|email
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    assignee_email: Mapped[str] = mapped_column(String(255), default="")
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True
    )
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ======================= Devis & factures =======================
class Counter(Base):
    __tablename__ = "counters"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)  # ex : "invoice-2026"
    value: Mapped[int] = mapped_column(Integer, default=0)


class BillingDoc(Base):
    __tablename__ = "billing_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # quote | invoice
    number: Mapped[str | None] = mapped_column(
        String(30), unique=True, nullable=True
    )  # attribué à l'émission
    status: Mapped[str] = mapped_column(String(12), default="draft")
    # quote : draft|sent|accepted|refused ; invoice : draft|sent|paid|cancelled
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True
    )
    source_quote_id: Mapped[int | None] = mapped_column(
        ForeignKey("billing_docs.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )  # échéance (facture) / validité (devis)
    notes: Mapped[str] = mapped_column(Text, default="")
    total_ht: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0)
    total_vat: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0)
    total_ttc: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0)
    amount_paid: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0)
    created_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    lines: Mapped[list["BillingLine"]] = relationship(
        cascade="all, delete-orphan", order_by="BillingLine.position", back_populates="doc"
    )
    payments: Mapped[list["Payment"]] = relationship(cascade="all, delete-orphan", back_populates="doc")


class BillingLine(Base):
    __tablename__ = "billing_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("billing_docs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[float] = mapped_column(Numeric(12, 3, asdecimal=False), default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0)
    vat_rate: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False), default=20)
    doc: Mapped[BillingDoc] = relationship(back_populates="lines")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("billing_docs.id", ondelete="CASCADE"), index=True)
    paid_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    method: Mapped[str] = mapped_column(String(40), default="Virement")
    note: Mapped[str] = mapped_column(String(300), default="")
    doc: Mapped[BillingDoc] = relationship(back_populates="payments")


# ======================= Abonnements, domaines, contrats =======================
class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(
        String(20), default="saas"
    )  # domain|hosting|saas|insurance|contract|other
    vendor: Mapped[str] = mapped_column(String(200), default="")
    cost: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0)  # HT par période
    period: Mapped[str] = mapped_column(String(10), default="yearly")  # monthly|quarterly|yearly
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    notice_days: Mapped[int] = mapped_column(Integer, default=30)  # alerte N jours avant
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")


# ======================= Trésorerie =======================
class BankAccount(Base):
    __tablename__ = "bank_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    initial_balance: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), default=0)
    iban: Mapped[str] = mapped_column(String(40), default="")
    provider: Mapped[str] = mapped_column(
        String(20), default="manual", server_default="manual"
    )  # manual | qonto
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id", ondelete="CASCADE"), index=True)
    tx_date: Mapped[date] = mapped_column(Date, index=True)
    label: Mapped[str] = mapped_column(String(300))
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))  # + encaissement / - décaissement
    category: Mapped[str] = mapped_column(String(80), default="")
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)  # id Qonto


# ======================= Temps =======================
class TimeEntry(Base):
    __tablename__ = "time_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_email: Mapped[str] = mapped_column(String(255), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    hours: Mapped[float] = mapped_column(Numeric(5, 2, asdecimal=False))
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str] = mapped_column(String(300), default="")
    billable: Mapped[bool] = mapped_column(Boolean, default=True)
    hourly_rate: Mapped[float | None] = mapped_column(
        Numeric(8, 2, asdecimal=False), nullable=True
    )  # taux de vente


# ======================= Équipe =======================
class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(255), default="", index=True)
    job_title: Mapped[str] = mapped_column(String(120), default="")
    contract: Mapped[str] = mapped_column(String(30), default="CDI")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    daily_cost: Mapped[float] = mapped_column(
        Numeric(8, 2, asdecimal=False), default=0
    )  # coût journalier chargé
    leave_days_per_year: Mapped[float] = mapped_column(Numeric(5, 1, asdecimal=False), default=25)
    notes: Mapped[str] = mapped_column(Text, default="")


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    days: Mapped[float] = mapped_column(Numeric(5, 1, asdecimal=False))
    kind: Mapped[str] = mapped_column(String(12), default="paid")  # paid|rtt|sick|unpaid
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|refused
    note: Mapped[str] = mapped_column(String(300), default="")
    decided_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="onboarding")  # onboarding|offboarding
    title: Mapped[str] = mapped_column(String(300))
    done: Mapped[bool] = mapped_column(Boolean, default=False)


# ======================= Documents & accès =======================
class FileRecord(Base):
    __tablename__ = "file_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(
        String(40), default="autre"
    )  # contrat|legal|assurance|facture|rh|autre
    original_name: Mapped[str] = mapped_column(String(300))
    stored_name: Mapped[str] = mapped_column(String(80), unique=True)
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(String(500), default="")
    uploaded_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AccessEntry(Base):
    """Registre des accès : OÙ est l'accès, jamais le mot de passe."""

    __tablename__ = "access_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    system: Mapped[str] = mapped_column(String(200))  # ex : OVH, GitHub, Google Workspace
    account: Mapped[str] = mapped_column(String(200), default="")
    secret_location: Mapped[str] = mapped_column(String(300), default="")  # ex : « Bitwarden > Deva2 > OVH »
    holders: Mapped[str] = mapped_column(String(300), default="")
    last_rotated: Mapped[date | None] = mapped_column(Date, nullable=True)
    rotate_every_days: Mapped[int] = mapped_column(Integer, default=365)
    notes: Mapped[str] = mapped_column(Text, default="")
