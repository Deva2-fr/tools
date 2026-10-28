from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Kind = Literal["prospect", "client", "supplier", "partner"]
Stage = Literal["prospect", "contact", "quote", "negotiation", "won", "lost"]
STAGE_DEFAULT_PROBA = {"prospect": 10, "contact": 25, "quote": 50, "negotiation": 75, "won": 100, "lost": 0}


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Kind = "prospect"
    siret: str = ""
    vat_number: str = ""
    website: str = ""
    sector: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = "France"
    tags: str = ""
    notes: str = ""


class ContactIn(BaseModel):
    company_id: int | None = None
    first_name: str = ""
    last_name: str = ""
    job_title: str = ""
    email: str = ""
    phone: str = ""
    tags: str = ""
    notes: str = ""

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class OpportunityIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company_id: int | None = None
    contact_id: int | None = None
    stage: Stage = "prospect"
    amount: float = Field(0, ge=0, lt=100_000_000)
    probability: int = Field(20, ge=0, le=100)
    expected_close: date | None = None
    owner_email: str = ""
    next_action: str = ""
    notes: str = ""


class StageIn(BaseModel):
    stage: Stage


class ActivityIn(BaseModel):
    kind: Literal["note", "call", "meeting", "email"] = "note"
    subject: str = Field(min_length=1, max_length=300)
    body: str = ""
    company_id: int | None = None
    contact_id: int | None = None
    opportunity_id: int | None = None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_date: date | None = None
    done: bool = False
    assignee_email: str = ""
    company_id: int | None = None
    contact_id: int | None = None
    opportunity_id: int | None = None
    notes: str = ""


class CsvImport(BaseModel):
    csv: str = Field(max_length=2_000_000)
