from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LineIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: float = Field(1, gt=0, lt=1_000_000)
    unit_price: float = Field(0, ge=-1_000_000, lt=100_000_000)
    vat_rate: float = Field(20, ge=0, le=100)


class LineOut(LineIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    position: int


class PaymentIn(BaseModel):
    paid_on: date
    amount: float = Field(gt=0, lt=100_000_000)
    method: str = "Virement"
    note: str = ""


class PaymentOut(PaymentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class DocIn(BaseModel):
    kind: Literal["quote", "invoice"]
    company_id: int | None = None
    contact_id: int | None = None
    opportunity_id: int | None = None
    title: str = ""
    issue_date: date
    due_date: date | None = None
    notes: str = ""
    lines: list[LineIn] = Field(default_factory=list, max_length=200)


class StatusIn(BaseModel):
    status: Literal["accepted", "refused", "cancelled", "sent"]


class DocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    number: str | None
    status: str
    company_id: int | None
    company_name: str = ""
    contact_id: int | None
    opportunity_id: int | None
    source_quote_id: int | None
    title: str
    issue_date: date
    due_date: date | None
    notes: str
    total_ht: float
    total_vat: float
    total_ttc: float
    amount_paid: float
    remaining: float = 0
    is_overdue: bool = False
    provider: str = "manual"
    external_url: str = ""
    qonto_editable: bool = False  # devis Qonto en attente : modifiable ici, reporté dans Qonto
    lines: list[LineOut] = []
    payments: list[PaymentOut] = []
    created_at: datetime
