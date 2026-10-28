from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth / users ----------
class LoginIn(BaseModel):
    email: str
    password: str
    totp_code: str | None = None


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    totp_enabled: bool


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    name: str = ""
    password: str = Field(min_length=12, max_length=200)
    role: Literal["admin", "manager", "member"] = "member"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=200)


class TotpCode(BaseModel):
    code: str


# ---------- projets ----------
class ServerIn(BaseModel):
    label: str = ""
    provider: str = ""
    hostname: str = ""
    ip: str = ""
    os: str = ""
    location: str = ""
    specs: str = ""
    access_info: str = ""
    notes: str = ""


class ServerOut(ServerIn, ORM):
    id: int
    project_id: int


class TechIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    version: str = ""
    category: str = ""
    watch_cve: bool = True


class TechOut(TechIn, ORM):
    id: int
    project_id: int
    last_scanned_at: datetime | None


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=4, max_length=500)
    description: str = ""
    environment: Literal["prod", "staging", "dev"] = "prod"
    repo_url: str = ""
    monitoring_tools: str = ""
    notes: str = ""
    monitoring_enabled: bool = True
    public_status: bool = False
    check_interval_min: int = Field(5, ge=1, le=1440)
    expected_status: int | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v


class ProjectOut(ProjectIn, ORM):
    id: int
    status: str
    last_checked_at: datetime | None
    last_latency_ms: int | None
    ssl_expires_at: datetime | None
    missing_headers: list[str]
    servers: list[ServerOut] = []
    technologies: list[TechOut] = []
    open_vulnerabilities: int = 0


class CheckOut(ORM):
    ts: datetime
    ok: bool
    status_code: int | None
    latency_ms: int | None
    error: str
    ssl_days_left: int | None


class VulnOut(ORM):
    id: int
    project_id: int
    cve_id: str
    cvss: float | None
    summary: str
    exploited: bool
    published_at: datetime | None
    dismissed: bool
    tech_name: str = ""
    tech_version: str = ""
    project_name: str = ""


# ---------- alertes ----------
class AlertOut(ORM):
    id: int
    project_id: int | None
    kind: str
    severity: str
    title: str
    message: str
    acknowledged: bool
    delivery: str
    created_at: datetime


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["email", "slack", "discord", "telegram", "webhook"]
    config: dict[str, str] = {}
    min_severity: Literal["info", "warning", "critical"] = "warning"
    enabled: bool = True


class ChannelOut(BaseModel):
    id: int
    name: str
    type: str
    min_severity: str
    enabled: bool
    config_keys: list[str]


# ---------- mails ----------
class MailOut(ORM):
    id: int
    mailbox_id: int | None = None
    subject: str
    sender_name: str
    sender_email: str
    preview: str
    web_link: str
    received_at: datetime
    is_read: bool
    tag: str


class MailboxIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field("", max_length=500)  # vide à la modification = inchangé
    sent_folder: str = Field("", max_length=255)
    webmail_url: str = Field("", max_length=500)
    position: int = 0
    active: bool = True


class MailTagIn(BaseModel):
    tag: Literal["a_repondre", "urgent", "fait", "ignore", "auto"]


# ---------- notes de frais ----------
class ExpenseIn(BaseModel):
    expense_date: date
    employee: str = ""
    reason: str = Field(min_length=1, max_length=300)
    category: str = ""
    project: str = ""
    payment_method: str = ""
    amount_ttc: float = Field(gt=0, lt=1_000_000)
    vat_rate: float = Field(20, ge=0, le=100)
    notes: str = ""
    user_id: int | None = None  # vide = soi-même
    signature_id: int | None = None  # demandeur
    president_signature_id: int | None = None
    partner_signature_id: int | None = None


class ExpenseOut(ExpenseIn, ORM):
    id: int
    amount_ht: float
    amount_vat: float
    has_pdf: bool = False
    receipt_files: list[dict] = []  # [{id, name}]
    drive_link: str = ""
    created_at: datetime


# ---------- impôts ----------
class TaxIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = "autre"
    due_date: date
    amount: float | None = None
    recurrence: Literal["none", "monthly", "quarterly", "yearly"] = "none"
    reminder_days: str = "30,7,1"
    notes: str = ""
    status: Literal["todo", "paid"] = "todo"


class TaxOut(TaxIn, ORM):
    id: int
    days_left: int = 0
